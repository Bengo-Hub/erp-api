"""
API endpoints for the centralized payment service
"""
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, action
from django.utils import timezone
from django.db import transaction
from rest_framework.pagination import PageNumberPagination
from decimal import Decimal, InvalidOperation

from .services import get_payment_service
from finance.accounts.models import PaymentAccounts
from .models import PaymentMethod, Payment, POSPayment, PaymentTransaction, PaymentRefund, BillingDocument, BillingDocumentHistory
from .serializers import (
    PaymentMethodSerializer,
    PaymentSerializer,
    POSPaymentSerializer,
    CreatePOSPaymentSerializer,
    PaymentTransactionSerializer,
    PaymentRefundSerializer,
    BillingDocumentSerializer,
    BillingDocumentHistorySerializer
)
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail, log_payment_operation
from core.validators import validate_non_negative_decimal
from core.base_viewsets import BaseModelViewSet
import logging

logger = logging.getLogger(__name__)

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class SplitPaymentView(APIView):
    """
    Endpoint to process payments using multiple payment methods for a single entity
    with comprehensive validation and audit logging.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, format=None):
        """
        Process multiple payments for a single entity (split payment)
        
        Required parameters:
        - entity_type: Type of entity (order, invoice, pos_sale)
        - entity_id: ID of the entity
        - payments: List of payment dictionaries, each containing:
            - amount: Payment amount (must be > 0)
            - payment_method: Payment method code (cash, mpesa, card, bank, etc.)
            - transaction_id: Optional transaction ID
            - transaction_details: Optional additional details
            - payment_account_id: Optional specific payment account to use
        """
        try:
            correlation_id = get_correlation_id(request)
            
            # Get required parameters
            entity_type = request.data.get('entity_type', '').strip()
            entity_id = request.data.get('entity_id')
            payments = request.data.get('payments', [])
            
            # Validate required parameters
            errors = {}
            
            if not entity_type:
                errors['entity_type'] = 'Entity type is required'
            if not entity_id:
                errors['entity_id'] = 'Entity ID is required'
            if not payments or not isinstance(payments, list) or len(payments) == 0:
                errors['payments'] = 'At least one payment record is required'
            
            if errors:
                return APIResponse.validation_error(
                    message='Split payment validation failed',
                    errors=errors,
                    correlation_id=correlation_id
                )
            
            # Validate individual payments
            payment_errors = []
            for idx, payment in enumerate(payments):
                payment_item_errors = {}
                
                # Validate amount
                try:
                    amount = Decimal(str(payment.get('amount', 0)))
                    if amount <= 0:
                        payment_item_errors['amount'] = 'Amount must be greater than 0'
                except (InvalidOperation, TypeError, ValueError):
                    payment_item_errors['amount'] = 'Invalid amount format'
                
                # Validate payment method
                payment_method = payment.get('payment_method', '').strip()
                if not payment_method:
                    payment_item_errors['payment_method'] = 'Payment method is required'
                
                if payment_item_errors:
                    payment_errors.append({'index': idx, 'errors': payment_item_errors})
            
            if payment_errors:
                return APIResponse.validation_error(
                    message='Payment validation failed',
                    errors={'payments': payment_errors},
                    correlation_id=correlation_id
                )
            
            # Process split payment
            payment_service = get_payment_service()

            # If branch header is provided, validate entity belongs to that branch
            try:
                from core.utils import get_branch_id_from_request
                header_branch_id = request.query_params.get('branch_id') or get_branch_id_from_request(request)
            except Exception:
                header_branch_id = None

            if header_branch_id:
                if entity_type == 'order':
                    from core_orders.models import BaseOrder as OrderModel
                    order = OrderModel.objects.filter(id=entity_id).first()
                    if order and order.branch_id and str(order.branch_id) != str(header_branch_id):
                        return APIResponse.forbidden(message='Order does not belong to the specified branch', correlation_id=correlation_id)
                elif entity_type == 'invoice':
                    bd = BillingDocument.objects.filter(id=entity_id).first()
                    if bd and bd.branch_id and str(bd.branch_id) != str(header_branch_id):
                        return APIResponse.forbidden(message='Invoice does not belong to the specified branch', correlation_id=correlation_id)
                elif entity_type == 'pos_sale':
                    sale = Sales.objects.filter(id=entity_id).select_related('register__branch').first()
                    sale_branch_id = sale.register.branch_id if sale and sale.register and sale.register.branch_id else None
                    if sale_branch_id and str(sale_branch_id) != str(header_branch_id):
                        return APIResponse.forbidden(message='POS sale does not belong to the specified branch', correlation_id=correlation_id)
            success, message, payment_records = payment_service.process_split_payment(
                entity_type=entity_type,
                entity_id=entity_id,
                payments=payments,
                created_by=request.user
            )
            
            # Log payment operation
            if success and payment_records:
                total_amount = sum(float(getattr(p, 'amount', 0)) for p in payment_records)
                AuditTrail.log(
                    operation=AuditTrail.PAYMENT,
                    module='finance',
                    entity_type=entity_type.capitalize(),
                    entity_id=entity_id,
                    user=request.user,
                    changes={
                        'payment_count': {'new': len(payment_records)},
                        'total_amount': {'new': total_amount}
                    },
                    reason=f'Split payment processed for {entity_type} {entity_id}',
                    request=request
                )
            
            # Return response based on payment result
            if success:
                return APIResponse.success(
                    data={
                        'entity_type': entity_type,
                        'entity_id': entity_id,
                        'payment_count': len(payment_records) if payment_records else 0,
                        'total_amount': sum(float(getattr(p, 'amount', 0)) for p in payment_records) if payment_records else 0
                    },
                    message=message or 'Split payment processed successfully',
                    status_code=status.HTTP_200_OK,
                    correlation_id=correlation_id
                )
            else:
                return APIResponse.error(
                    error_code='PAYMENT_PROCESSING_FAILED',
                    message=message or 'Failed to process split payment',
                    status_code=status.HTTP_400_BAD_REQUEST,
                    correlation_id=correlation_id
                )
        
        except Exception as e:
            logger.error(f"Error processing split payment: {str(e)}", exc_info=True)
            correlation_id = get_correlation_id(request)
            return APIResponse.server_error(
                message='Error processing split payment',
                error_id=str(e),
                correlation_id=correlation_id
            )


class ProcessPaymentView(APIView):
    """
    Endpoint to process payments for any entity in the system
    with comprehensive validation and audit logging.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, format=None):
        """
        Process a payment from any module
        
        Required parameters:
        - entity_type: Type of entity (order, invoice, pos_sale)
        - entity_id: ID of the entity
        - amount: Amount to pay (must be > 0)
        - payment_method: Payment method code (cash, mpesa, card, bank, etc.)
        
        Optional parameters:
        - transaction_id: External transaction ID
        - transaction_details: Additional payment details
        - payment_account_id: ID of the payment account to use
        - notes: Payment notes
        """
        try:
            correlation_id = get_correlation_id(request)
            
            # Get required parameters
            entity_type = request.data.get('entity_type', '').strip()
            entity_id = request.data.get('entity_id')
            amount = request.data.get('amount')
            payment_method = request.data.get('payment_method', '').strip()
            
            # Validate required parameters
            errors = {}
            
            if not entity_type:
                errors['entity_type'] = 'Entity type is required'
            if not entity_id:
                errors['entity_id'] = 'Entity ID is required'
            if not payment_method:
                errors['payment_method'] = 'Payment method is required'
            
            # Validate and parse amount
            try:
                amount_decimal = validate_non_negative_decimal(amount, 'amount')
                if amount_decimal <= 0:
                    errors['amount'] = 'Amount must be greater than 0'
            except Exception as e:
                errors['amount'] = str(e)
            
            if errors:
                return APIResponse.validation_error(
                    message='Payment validation failed',
                    errors=errors,
                    correlation_id=correlation_id
                )
            
            # Get optional parameters
            transaction_id = request.data.get('transaction_id')
            transaction_details = request.data.get('transaction_details')
            payment_account_id = request.data.get('payment_account_id')
            notes = request.data.get('notes', '')
            
            # Get the payment account if specified
            payment_account = None
            if payment_account_id:
                try:
                    payment_account = PaymentAccounts.objects.get(id=payment_account_id)
                except PaymentAccounts.DoesNotExist:
                    return APIResponse.error(
                        error_code='PAYMENT_ACCOUNT_NOT_FOUND',
                        message=f'Payment account {payment_account_id} not found',
                        status_code=status.HTTP_404_NOT_FOUND,
                        correlation_id=correlation_id
                    )
            
            # Process the payment
            payment_service = get_payment_service()

            # If a branch header is provided, validate that the target entity belongs to that branch
            try:
                from core.utils import get_branch_id_from_request
                header_branch_id = request.query_params.get('branch_id') or get_branch_id_from_request(request)
            except Exception:
                header_branch_id = None

            if header_branch_id:
                # Validate common entity types
                if entity_type == 'order':
                    from core_orders.models import BaseOrder as OrderModel
                    order = OrderModel.objects.filter(id=entity_id).first()
                    if order and order.branch_id and str(order.branch_id) != str(header_branch_id):
                        return APIResponse.forbidden(message='Order does not belong to the specified branch', correlation_id=correlation_id)
                elif entity_type == 'invoice':
                    bd = BillingDocument.objects.filter(id=entity_id).first()
                    if bd and bd.branch_id and str(bd.branch_id) != str(header_branch_id):
                        return APIResponse.forbidden(message='Invoice does not belong to the specified branch', correlation_id=correlation_id)
                elif entity_type == 'pos_sale':
                    sale = Sales.objects.filter(id=entity_id).select_related('register__branch').first()
                    sale_branch_id = sale.register.branch_id if sale and sale.register and sale.register.branch_id else None
                    if sale_branch_id and str(sale_branch_id) != str(header_branch_id):
                        return APIResponse.forbidden(message='POS sale does not belong to the specified branch', correlation_id=correlation_id)
            success, message, payment_record = payment_service.process_payment(
                entity_type=entity_type,
                entity_id=entity_id,
                amount=amount_decimal,
                payment_method=payment_method,
                transaction_id=transaction_id,
                transaction_details=transaction_details,
                payment_account=payment_account,
                created_by=request.user,
                notes=notes
            )
            
            # Log payment operation
            if success:
                log_payment_operation(
                    payment_id=getattr(payment_record, 'id', entity_id),
                    amount=float(amount_decimal),
                    method=payment_method,
                    status='completed',
                    user=request.user,
                    reference=transaction_id,
                    request=request
                )
            
            if success:
                return APIResponse.success(
                    data={
                        'entity_type': entity_type,
                        'entity_id': entity_id,
                        'amount': float(amount_decimal),
                        'payment_method': payment_method,
                        'transaction_id': transaction_id,
                        'status': 'completed'
                    },
                    message=message or 'Payment processed successfully',
                    status_code=status.HTTP_200_OK,
                    correlation_id=correlation_id
                )
            else:
                return APIResponse.error(
                    error_code='PAYMENT_PROCESSING_FAILED',
                    message=message or 'Failed to process payment',
                    status_code=status.HTTP_400_BAD_REQUEST,
                    correlation_id=correlation_id
                )
        
        except Exception as e:
            logger.error(f"Error processing payment: {str(e)}", exc_info=True)
            correlation_id = get_correlation_id(request)
            return APIResponse.server_error(
                message='Error processing payment',
                error_id=str(e),
                correlation_id=correlation_id
            )


class MpesaPaymentView(APIView):
    """
    Endpoint to process M-Pesa payments for any entity
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, format=None):
        """
        Process an M-Pesa payment
        
        Required parameters:
        - phone_number: Customer phone number
        - amount: Amount to pay
        - reference_id: Reference ID (order_id, invoice_number, etc.)
        - entity_type: Type of entity (order, invoice, pos_sale)
        
        Optional parameters:
        - mpesa_receipt: M-Pesa receipt number
        - entity_id: Entity ID (if different from reference_id)
        - payment_account_id: ID of the payment account to use
        """
        # Get required parameters
        phone_number = request.data.get('phone_number')
        amount = request.data.get('amount')
        reference_id = request.data.get('reference_id')
        entity_type = request.data.get('entity_type')
        
        # Validate required parameters
        if not all([phone_number, amount, reference_id, entity_type]):
            return Response({
                'success': False,
                'message': 'Missing required parameters',
                'required': ['phone_number', 'amount', 'reference_id', 'entity_type']
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # Get optional parameters
        mpesa_receipt = request.data.get('mpesa_receipt')
        entity_id = request.data.get('entity_id')
        payment_account_id = request.data.get('payment_account_id')
        
        # Get the payment account if specified
        payment_account = None
        if payment_account_id:
            try:
                payment_account = PaymentAccounts.objects.get(id=payment_account_id)
            except PaymentAccounts.DoesNotExist:
                return Response({
                    'success': False,
                    'message': f'Payment account with ID {payment_account_id} not found'
                }, status=status.HTTP_404_NOT_FOUND)
        
        # Get payment service with the specified account
        payment_service = get_payment_service(payment_account)
        
        # Process M-Pesa payment
        success, message, payment = payment_service.process_mpesa_payment(
            phone_number=phone_number,
            amount=amount,
            reference_id=reference_id,
            mpesa_receipt=mpesa_receipt,
            entity_type=entity_type,
            entity_id=entity_id,
            created_by=request.user
        )
        
        # Return response based on payment result
        if success:
            # Try to send M-Pesa SMS notification without affecting main flow
            try:
                from integrations.services import get_sms_service  # type: ignore
                sms = get_sms_service()
                message = f"Payment received: KES {amount} via M-Pesa, Ref {mpesa_receipt or getattr(payment, 'transaction_id', '')}."
                if phone_number:
                    sms.send_sms(to=phone_number, message=message)  # SMS service handles async by default
            except Exception:
                pass
            return Response({
                'success': True,
                'message': message,
                'data': {
                    'reference_id': reference_id,
                    'entity_type': entity_type,
                    'entity_id': entity_id or reference_id,
                    'amount': amount,
                    'mpesa_receipt': mpesa_receipt or getattr(payment, 'transaction_id', None),
                    'payment_id': getattr(payment, 'id', None)
                }
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'message': message
            }, status=status.HTTP_400_BAD_REQUEST)


class MpesaCallbackView(APIView):
    """
    Handle M-Pesa callbacks from the payment provider
    This endpoint should be configured in the M-Pesa developer portal
    """
    permission_classes = []  # No authentication for callbacks
    
    def post(self, request, format=None):
        """Process M-Pesa callback data"""
        try:
            # Get callback data from request
            callback_data = request.data
            
            # Process callback through payment service
            payment_service = get_payment_service()
            success, message, payment = payment_service.verify_mpesa_callback(callback_data)
            
            if success:
                # Successful processing
                return Response({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted"
                }, status=status.HTTP_200_OK)
            else:
                # Failed processing but still return OK to M-Pesa
                return Response({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted"
                }, status=status.HTTP_200_OK)
                
        except Exception as e:
            # Log error but still return OK to M-Pesa
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error processing M-Pesa callback: {str(e)}")
            
            return Response({
                "ResultCode": 0,
                "ResultDesc": "Accepted"
            }, status=status.HTTP_200_OK)


# Airtel Money support removed per business requirements

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payment_accounts(request):
    """Get all available payment accounts"""
    accounts = PaymentAccounts.objects.all()
    data = [{
        'name': account.name,
        'account_number': account.account_number,
        'account_type': account.account_type.name if account.account_type else None
    } for account in accounts]
    
    return Response({
        'success': True,
        'data': data
    }, status=status.HTTP_200_OK)

class PaymentMethodViewSet(BaseModelViewSet):
    queryset = PaymentMethod.objects.filter(is_active=True)
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAuthenticated]

class PaymentViewSet(BaseModelViewSet):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        # Add filters based on query parameters
        status = self.request.GET.get('status', None)
        if status:
            queryset = queryset.filter(status=status)
        
        document_id = self.request.GET.get('document_id', None)
        if document_id:
            queryset = queryset.filter(document_id=document_id)

        # Branch scoping via related billing document
        try:
            from core.utils import get_branch_id_from_request
            branch_id = self.request.query_params.get('branch_id') or get_branch_id_from_request(self.request)
        except Exception:
            branch_id = None

        if branch_id:
            queryset = queryset.filter(document__branch_id=branch_id)

        return queryset

class POSPaymentViewSet(BaseModelViewSet):
    queryset = POSPayment.objects.all()
    permission_classes = [IsAuthenticated]

    serializer_class = POSPaymentSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        try:
            from core.utils import get_branch_id_from_request
            branch_id = self.request.query_params.get('branch_id') or get_branch_id_from_request(self.request)
        except Exception:
            branch_id = None

        if branch_id:
            queryset = queryset.filter(sale__register__branch_id=branch_id)

        return queryset

    @action(detail=False, methods=['post'])
    def process_sale(self, request):
        with transaction.atomic():
            serializer = CreatePOSPaymentSerializer(data=request.data)
            if serializer.is_valid():
                payment = serializer.save()
                return Response(POSPaymentSerializer(payment).data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def refund(self, request, pk=None):
        payment = self.get_object()
        refund_data = {
            'payment': payment,
            'amount': request.data.get('amount'),
            'reason': request.data.get('reason'),
            'processed_by': request.user
        }
        
        with transaction.atomic():
            refund = PaymentRefund.objects.create(**refund_data)
            payment.status = 'refunded'
            payment.save()
            
            # Update sale status if needed
            if payment.sale:
                payment.sale.payment_status = 'refunded'
                payment.sale.save()
                
            return Response(PaymentRefundSerializer(refund).data)

class PaymentTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PaymentTransaction.objects.all()
    serializer_class = PaymentTransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        payment_id = self.request.GET.get('payment', None)
        if payment_id:
            queryset = queryset.filter(payment_id=payment_id)
        return queryset

class PaymentRefundViewSet(viewsets.ModelViewSet):
    queryset = PaymentRefund.objects.all()
    serializer_class = PaymentRefundSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        refund = self.get_object()
        refund.status = 'completed'
        refund.save()
        return Response({'status': 'refund processed'})

class BillingDocumentViewSet(viewsets.ModelViewSet):
    queryset = BillingDocument.objects.all()
    serializer_class = BillingDocumentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        try:
            from core.utils import get_branch_id_from_request
            branch_id = self.request.query_params.get('branch_id') or get_branch_id_from_request(self.request)
        except Exception:
            branch_id = None

        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        if not self.request.user.is_superuser:
            from business.models import Branch
            user = self.request.user
            owned_branches = Branch.objects.filter(business__owner=user)
            employee_branches = Branch.objects.filter(business__employees__user=user)
            branches = owned_branches | employee_branches
            queryset = queryset.filter(branch__in=branches)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)
    
    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, pk=None):
        """Return a PDF representation of this billing document for preview or download."""
        try:
            from django.http import HttpResponse
            from finance.payment import pdf_utils
            document = self.get_object()
            # Use invoice generator for INVOICE, receipt for RECEIPT, and generic invoice for others
            if document.document_type == BillingDocument.INVOICE:
                pdf_bytes = pdf_utils.download_invoice_pdf(document.id)
            elif document.document_type == BillingDocument.RECEIPT:
                # Build receipt data inline for simplicity and generate
                receipt_data = {
                    'receipt_number': document.document_number,
                    'receipt_date': document.issue_date,
                    'customer_name': str(document.customer) if document.customer else None,
                    'items': [
                        {
                            'description': item.description,
                            'quantity': item.quantity,
                            'unit_price': item.unit_price,
                            'total': item.total
                        } for item in document.items.all()
                    ],
                    'subtotal': document.subtotal or 0,
                    'tax': document.tax_amount or 0,
                    'total': document.total,
                    'payment_method': ''
                }
                pdf_bytes = pdf_utils.generate_receipt_pdf(receipt_data)
            else:
                # Default to invoice PDF formatting
                pdf_bytes = pdf_utils.download_invoice_pdf(document.id)

            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            filename = f"{document.document_number}.pdf"
            # Allow preview inline; client may set download query param to force attachment
            disposition = 'attachment' if request.query_params.get('download', '').lower() in ['1', 'true', 'yes'] else 'inline'
            response['Content-Disposition'] = f"{disposition}; filename=\"{filename}\""
            return response
        except Exception as exc:
            logger.error(f"Error generating PDF for BillingDocument {pk}: {str(exc)}", exc_info=True)
            return Response({'detail': 'Failed to generate PDF', 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # add_payment endpoint removed in favor of ProcessPaymentView

    @action(detail=True, methods=['post'], url_path='submit-kra')
    def submit_kra(self, request, pk=None):
        """Submit this invoice to KRA eTIMS using integrations service."""
        document = self.get_object()
        if document.document_type != BillingDocument.INVOICE:
            return Response({'detail': 'Only invoices can be submitted to KRA'}, status=status.HTTP_400_BAD_REQUEST)

        invoice_payload = request.data.get('invoice_payload')
        if not isinstance(invoice_payload, dict) or not invoice_payload:
            # build from billing document if not provided
            try:
                from integrations.utils_api import build_kra_invoice_payload_from_billing_document
                invoice_payload = build_kra_invoice_payload_from_billing_document(document)
            except Exception:
                return Response({'detail': 'invoice_payload is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.submit_invoice(invoice_payload)
            if ok:
                return Response({'success': True, 'result': result})
            return Response({'success': False, 'error': result}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'success': False, 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)