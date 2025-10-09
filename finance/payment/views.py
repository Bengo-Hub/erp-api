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

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class SplitPaymentView(APIView):
    """
    Endpoint to process payments using multiple payment methods for a single entity
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, format=None):
        """
        Process multiple payments for a single entity (split payment)
        
        Required parameters:
        - entity_type: Type of entity (order, invoice, pos_sale)
        - entity_id: ID of the entity
        - payments: List of payment dictionaries, each containing:
            - amount: Payment amount
            - payment_method: Payment method code
            - transaction_id: Optional transaction ID
            - transaction_details: Optional additional details
            - payment_account_id: Optional specific payment account to use
        """
        # Get required parameters
        entity_type = request.data.get('entity_type')
        entity_id = request.data.get('entity_id')
        payments = request.data.get('payments', [])
        
        # Validate required parameters
        if not entity_type or not entity_id:
            return Response({
                'success': False,
                'message': 'Missing required parameters: entity_type and entity_id',
            }, status=status.HTTP_400_BAD_REQUEST)
            
        if not payments or not isinstance(payments, list) or len(payments) == 0:
            return Response({
                'success': False,
                'message': 'No payment records provided or invalid format',
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # Process split payment
        payment_service = get_payment_service()
        success, message, payment_records = payment_service.process_split_payment(
            entity_type=entity_type,
            entity_id=entity_id,
            payments=payments,
            created_by=request.user
        )
        
        # Return response based on payment result
        if success:
            return Response({
                'success': True,
                'message': message,
                'data': {
                    'entity_type': entity_type,
                    'entity_id': entity_id,
                    'payment_count': len(payment_records) if payment_records else 0,
                    'total_amount': sum(float(getattr(p, 'amount', 0)) for p in payment_records) if payment_records else 0
                }
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'message': message
            }, status=status.HTTP_400_BAD_REQUEST)


class ProcessPaymentView(APIView):
    """
    Endpoint to process payments for any entity in the system
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, format=None):
        """
        Process a payment from any module
        
        Required parameters:
        - entity_type: Type of entity (order, invoice, pos_sale)
        - entity_id: ID of the entity
        - amount: Amount to pay
        - payment_method: Payment method code (cash, mpesa, card, bank, etc.)
        
        Optional parameters:
        - transaction_id: External transaction ID
        - transaction_details: Additional payment details
        - payment_account_id: ID of the payment account to use
        - notes: Payment notes
        """
        # Get required parameters
        entity_type = request.data.get('entity_type')
        entity_id = request.data.get('entity_id')
        amount = request.data.get('amount')
        payment_method = request.data.get('payment_method')
        
        # Validate required parameters
        if not all([entity_type, entity_id, amount, payment_method]):
            return Response({
                'success': False,
                'message': 'Missing required parameters',
                'required': ['entity_type', 'entity_id', 'amount', 'payment_method']
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # Get optional parameters
        transaction_id = request.data.get('transaction_id')
        transaction_details = request.data.get('transaction_details')
        payment_account_id = request.data.get('payment_account_id')
        notes = request.data.get('notes')
        
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
        
        # Process payment based on entity type
        if entity_type == 'order':
            from core_orders.models import BaseOrder
            try:
                order = BaseOrder.objects.get(order_id=entity_id)
                success, message, payment = payment_service.process_order_payment(
                    order=order,
                    amount=amount,
                    payment_method=payment_method,
                    transaction_id=transaction_id,
                    transaction_details=transaction_details,
                    created_by=request.user
                )
            except BaseOrder.DoesNotExist:
                return Response({
                    'success': False,
                    'message': f'Order with ID {entity_id} not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
        elif entity_type == 'invoice':
            from finance.payment.models import BillingDocument
            try:
                invoice = BillingDocument.objects.get(document_number=entity_id)
                success, message, payment = payment_service.process_bill_payment(
                    document=invoice,
                    amount=amount,
                    payment_method=payment_method,
                    reference=transaction_id,
                    notes=notes,
                    created_by=request.user
                )
            except BillingDocument.DoesNotExist:
                return Response({
                    'success': False,
                    'message': f'Invoice with number {entity_id} not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
        elif entity_type == 'pos_sale':
            from ecommerce.pos.models import Sales
            try:
                sale = Sales.objects.get(sale_id=entity_id)
                success, message, payment = payment_service.process_pos_payment(
                    sale=sale,
                    amount=amount,
                    payment_method=payment_method,
                    transaction_id=transaction_id,
                    transaction_details=transaction_details,
                    created_by=request.user
                )
            except Sales.DoesNotExist:
                return Response({
                    'success': False,
                    'message': f'Sale with ID {entity_id} not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
        else:
            return Response({
                'success': False,
                'message': f'Unsupported entity type: {entity_type}'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # Return response based on payment result
        if success:
            return Response({
                'success': True,
                'message': message,
                'data': {
                    'entity_type': entity_type,
                    'entity_id': entity_id,
                    'amount': amount,
                    'payment_method': payment_method,
                    'payment_id': getattr(payment, 'id', None)
                }
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'message': message
            }, status=status.HTTP_400_BAD_REQUEST)


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

class PaymentMethodViewSet(viewsets.ModelViewSet):
    queryset = PaymentMethod.objects.filter(is_active=True)
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAuthenticated]

class PaymentViewSet(viewsets.ModelViewSet):
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

        return queryset

class POSPaymentViewSet(viewsets.ModelViewSet):
    queryset = POSPayment.objects.all()
    permission_classes = [IsAuthenticated]

    serializer_class = POSPaymentSerializer

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
        # ... (filtering logic from billing/views.py)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)
    
    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

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