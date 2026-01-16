#views
from rest_framework import viewsets
from .models import PurchaseOrder, PurchaseOrderPayment
from .serializers import PurchaseOrderSerializer, PurchaseOrderListSerializer, PurchaseOrderPaymentSerializer, PurchaseOrderCreateSerializer
from rest_framework import permissions
from rest_framework import filters
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Q
from decimal import Decimal
from rest_framework import status
from rest_framework.pagination import LimitOffsetPagination
from django.db import transaction
from procurement.purchases.models import *
from procurement.requisitions.models import *
from core.models import Departments
from .functions import generate_purchase_order
from business.models import Branch
from rest_framework.views import APIView
from django.utils import timezone
from django.http import HttpResponse
from core.base_viewsets import BaseModelViewSet
from core.utils import get_branch_id_from_request, get_business_id_from_request
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
from finance.pdf_generator import generate_lpo_pdf
import logging

logger = logging.getLogger(__name__)


def send_po_notification(purchase_order, notification_type, action_user, additional_message=None):
    """
    Send notification for Purchase Order workflow events.

    Args:
        purchase_order: The PurchaseOrder instance
        notification_type: Type of notification ('created', 'submitted', 'approved', 'rejected', 'received', 'cancelled')
        action_user: The user who performed the action
        additional_message: Optional additional context message
    """
    try:
        from notifications.services.notification_service import NotificationService
        from django.contrib.auth import get_user_model
        from approvals.utils import get_approvers_for_permission

        User = get_user_model()
        notification_service = NotificationService()

        # Get supplier name
        supplier_name = 'Unknown Supplier'
        if purchase_order.supplier:
            if purchase_order.supplier.user:
                supplier_name = f"{purchase_order.supplier.user.first_name} {purchase_order.supplier.user.last_name}".strip()
            if not supplier_name or supplier_name == '':
                supplier_name = purchase_order.supplier.name or 'Unknown Supplier'

        # Build base context
        context = {
            'order_number': purchase_order.order_number,
            'supplier_name': supplier_name,
            'total': str(purchase_order.total),
            'currency': purchase_order.currency,
            'action_user_name': f"{action_user.first_name} {action_user.last_name}".strip() or action_user.username,
        }

        action_url = f"/procurement/purchase-orders/{purchase_order.id}"

        if notification_type == 'created':
            # Notify procurement managers about new PO
            title = f"New Purchase Order: {purchase_order.order_number}"
            message = f"A new purchase order has been created for {context['supplier_name']}.\n\nTotal: {context['currency']} {context['total']}"
            recipients = get_approvers_for_permission('procurement.view_purchaseorder')

        elif notification_type == 'submitted':
            # Notify approvers about submitted PO
            title = f"PO Pending Approval: {purchase_order.order_number}"
            message = f"A purchase order for {context['supplier_name']} has been submitted for approval.\n\nTotal: {context['currency']} {context['total']}"
            recipients = get_approvers_for_permission('procurement.approve_purchaseorder')

        elif notification_type == 'approved':
            # Notify creator about approval
            title = f"Purchase Order Approved: {purchase_order.order_number}"
            message = f"Your purchase order for {context['supplier_name']} has been approved by {context['action_user_name']}."
            if additional_message:
                message += f"\n\n{additional_message}"
            recipients = [purchase_order.created_by] if purchase_order.created_by else []

        elif notification_type == 'rejected':
            # Notify creator about rejection
            title = f"Purchase Order Rejected: {purchase_order.order_number}"
            message = f"Your purchase order for {context['supplier_name']} has been rejected by {context['action_user_name']}."
            if additional_message:
                message += f"\n\nReason: {additional_message}"
            recipients = [purchase_order.created_by] if purchase_order.created_by else []

        elif notification_type == 'received':
            # Notify finance about received goods
            title = f"Goods Received: {purchase_order.order_number}"
            message = f"Goods for purchase order {purchase_order.order_number} from {context['supplier_name']} have been received.\n\nInventory has been updated."
            recipients = get_approvers_for_permission('finance.view_payment')

        elif notification_type == 'cancelled':
            # Notify relevant parties about cancellation
            title = f"Purchase Order Cancelled: {purchase_order.order_number}"
            message = f"Purchase order {purchase_order.order_number} for {context['supplier_name']} has been cancelled by {context['action_user_name']}."
            if additional_message:
                message += f"\n\nReason: {additional_message}"
            recipients = [purchase_order.created_by] if purchase_order.created_by else []

        elif notification_type == 'payment_recorded':
            # Notify creator about payment
            title = f"Payment Recorded: {purchase_order.order_number}"
            payment_amount = additional_message or context['total']
            message = f"A payment of {context['currency']} {payment_amount} has been recorded for PO {purchase_order.order_number}."
            recipients = [purchase_order.created_by] if purchase_order.created_by else []
            # Also notify finance team
            finance_approvers = get_approvers_for_permission('finance.view_payment')
            recipients.extend(finance_approvers)

        else:
            logger.warning(f"Unknown PO notification type: {notification_type}")
            return

        # Send notifications to all recipients
        for recipient in recipients:
            if isinstance(recipient, int):
                try:
                    recipient = User.objects.get(id=recipient)
                except User.DoesNotExist:
                    continue

            # Skip sending notification to the user who performed the action
            if recipient and recipient.id == action_user.id:
                continue

            try:
                notification_service.send_notification(
                    user=recipient,
                    title=title,
                    message=message,
                    notification_type='ORDER',
                    channels=['in_app', 'email'],
                    action_url=action_url,
                    data={
                        'purchase_order_id': purchase_order.id,
                        'order_number': purchase_order.order_number,
                        'event_type': notification_type
                    },
                    async_send=False
                )
            except Exception as e:
                logger.error(f"Failed to send PO notification to {recipient.username}: {str(e)}")

    except ImportError as e:
        logger.warning(f"Notification service not available: {str(e)}")
    except Exception as e:
        logger.error(f"Error sending PO notification: {str(e)}", exc_info=True)


class PurchaseOrderViewSet(BaseModelViewSet):
    # Optimized queryset with select_related and prefetch_related to prevent N+1 queries
    queryset = PurchaseOrder.objects.select_related(
        'created_by',
        'supplier__user',
        'requisition',
        'branch',
    ).prefetch_related(
        'approvals__approver',
        'items__content_type',
        'po_payments',
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering_fields = ['created_at']
    search_fields = ['order_number', 'status']

    def get_queryset(self):
        """Optimize queries with select_related for related objects."""
        from core.utils import get_user_business_and_branch
        from business.models import Bussiness

        queryset = super().get_queryset()

        # Filter by params
        approver = self.request.query_params.get('approver', None)
        status_filter = self.request.query_params.get('status', None)

        if approver:
            queryset = queryset.filter(approvals__approver_id=approver)

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Get business and branch context using unified utility (headers + user fallback)
        business, branch = get_user_business_and_branch(self.request, return_objects=True)
        branch_id = self.request.query_params.get('branch_id') or (branch.id if branch else None)

        # Filter by branch if explicitly specified
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        if not self.request.user.is_superuser:
            user = self.request.user

            # Get user's associated businesses using the same pattern as requisitions
            owned_businesses = Bussiness.objects.filter(owner=user)
            employee_businesses = Bussiness.objects.filter(employees__user=user)
            user_businesses = owned_businesses | employee_businesses

            # Get branches belonging to user's businesses
            user_branches = Branch.objects.filter(business__in=user_businesses)

            # Include POs where:
            # 1. Branch is in user's branches
            # 2. Created by user
            # 3. Branch is null (for backwards compatibility with older records)
            queryset = queryset.filter(
                Q(branch__in=user_branches) |
                Q(created_by=user) |
                Q(branch__isnull=True)
            ).distinct()

        return queryset 

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PurchaseOrderCreateSerializer
        if self.action == 'list':
            return PurchaseOrderListSerializer
        return PurchaseOrderSerializer

    def get_serializer_context(self):
        """
        Add extra context to the serializer. The context added is
        include_requisition_details, which is a boolean indicating whether
        to include the details of the purchase requisition in the
        serializer output. The default is False.
        """
        context = super().get_serializer_context()
        context['include_requisition_details'] = self.request.query_params.get(
            'include_requisition', 'false'
        ).lower() == 'true'
        return context

    def perform_create(self, serializer):
        # Get branch from request headers or user context if not in payload
        from core.utils import get_user_branch

        branch = serializer.validated_data.get('branch')
        if not branch:
            branch = get_user_branch(self.request.user, self.request)

        purchase_order = serializer.save(
            created_by=self.request.user,
            branch=branch,
            order_type='purchase_order',  # Required field from BaseOrder
            source='procurement'  # Set source to procurement
        )
        # Determine notification type based on status
        if purchase_order.status in ['submitted', 'pending']:
            send_po_notification(purchase_order, 'submitted', self.request.user)
        else:
            send_po_notification(purchase_order, 'created', self.request.user)

    @action(detail=True, methods=['post'], url_path='submit', name='submit')
    def submit(self, request, pk=None):
        """
        Submit a draft purchase order for approval.
        Changes status from 'draft' to 'submitted' and notifies approvers.
        """
        try:
            correlation_id = get_correlation_id(request)
            with transaction.atomic():
                order = self.get_object()

                if order.status != 'draft':
                    return APIResponse.bad_request(
                        message=f'Only draft purchase orders can be submitted. Current status: {order.status}',
                        error_id='invalid_order_status',
                        correlation_id=correlation_id
                    )

                # Update order status
                order.status = 'submitted'
                order.save()

                # Log submission
                AuditTrail.log(
                    operation=AuditTrail.SUBMIT,
                    module='procurement',
                    entity_type='PurchaseOrder',
                    entity_id=order.id,
                    user=request.user,
                    reason=f'Purchase order {order.order_number} submitted for approval',
                    request=request
                )

                # Send notification about submission
                send_po_notification(order, 'submitted', request.user)

                return APIResponse.success(
                    data=self.get_serializer(order).data,
                    message='Purchase order submitted for approval',
                    correlation_id=correlation_id
                )
        except Exception as e:
            logger.error(f'Error submitting purchase order: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error submitting purchase order',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'], url_path='approve', name='approve')
    def approve(self, request, pk=None):
        """
        Approve a purchase order by a user from procurement/finance department.
        Simple approval - directly updates order status without complex workflow.
        """
        try:
            correlation_id = get_correlation_id(request)
            with transaction.atomic():
                order = self.get_object()
                department = request.data.get('department', 'Procurement')
                notes = request.data.get('notes', f'Approved by {request.user.username}')

                if department.lower() not in ['procurement', 'finance']:
                    return APIResponse.forbidden(
                        message='Only procurement/finance can approve',
                        correlation_id=correlation_id
                    )

                # Update order status and approval info
                order.status = 'approved'
                order.approved_by = request.user
                order.approved_at = timezone.now()
                order.save(update_fields=['status', 'approved_by', 'approved_at'])

                # Log approval
                AuditTrail.log(
                    operation=AuditTrail.APPROVAL,
                    module='procurement',
                    entity_type='PurchaseOrder',
                    entity_id=order.id,
                    user=request.user,
                    reason=f'Purchase order {order.order_number} approved by {department}. Notes: {notes}',
                    request=request
                )

                # Send notification about approval
                send_po_notification(order, 'approved', request.user)

                return APIResponse.success(
                    data=self.get_serializer(order).data,
                    message='Purchase order approved successfully',
                    correlation_id=correlation_id
                )
        except Exception as e:
            logger.error(f'Error approving purchase order: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error approving purchase order',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'], url_path='reject', name='reject')
    def reject(self, request, pk=None):
        """Reject a purchase order - simple rejection without complex workflow."""
        try:
            correlation_id = get_correlation_id(request)
            with transaction.atomic():
                order = self.get_object()
                notes = request.data.get('notes', f'Rejected by {request.user.username}')

                # Update order status
                order.status = 'rejected'
                order.save(update_fields=['status'])

                # Log rejection
                AuditTrail.log(
                    operation=AuditTrail.CANCEL,
                    module='procurement',
                    entity_type='PurchaseOrder',
                    entity_id=order.id,
                    user=request.user,
                    reason=f'Purchase order {order.order_number} rejected. Notes: {notes}',
                    request=request
                )

                # Send notification about rejection
                send_po_notification(order, 'rejected', request.user, notes)

                return APIResponse.success(
                    data=self.get_serializer(order).data,
                    message='Purchase order rejected',
                    correlation_id=correlation_id
                )
        except Exception as e:
            logger.error(f'Error rejecting purchase order: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error rejecting purchase order',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'], url_path='cancel', name='cancel')
    def cancel(self, request, pk=None):
        """Cancel a purchase order."""
        try:
            correlation_id = get_correlation_id(request)
            with transaction.atomic():
                order = self.get_object()
                
                if order.status in ['completed', 'cancelled']:
                    return APIResponse.bad_request(
                        message=f'Cannot cancel purchase order with status: {order.status}',
                        error_id='invalid_order_status',
                        correlation_id=correlation_id
                    )
                
                # Update order status
                order.status = 'cancelled'
                order.save()
                
                # Log cancellation
                AuditTrail.log(
                    operation=AuditTrail.CANCEL,
                    module='procurement',
                    entity_type='PurchaseOrder',
                    entity_id=order.id,
                    user=request.user,
                    reason=f'Purchase order {order.order_number} cancelled',
                    request=request
                )

                # Send notification about cancellation
                send_po_notification(order, 'cancelled', request.user)

                return APIResponse.success(
                    data=self.get_serializer(order).data,
                    message='Purchase order cancelled successfully',
                    correlation_id=correlation_id
                )
        except Exception as e:
            logger.error(f'Error cancelling purchase order: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error cancelling purchase order',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'], url_path='mark-received', name='mark_received')
    def mark_received(self, request, pk=None):
        """
        Mark purchase order as received
        CRITICAL: Triggers inventory stock increase
        """
        try:
            correlation_id = get_correlation_id(request)
            with transaction.atomic():
                purchase_order = self.get_object()
                
                if purchase_order.status == 'received':
                    return APIResponse.bad_request(
                        message='Purchase order is already marked as received',
                        correlation_id=correlation_id
                    )
                
                # Mark as received (this triggers inventory update via signal/Purchase)
                purchase_order.mark_as_received()
                
                # Log receipt
                AuditTrail.log(
                    operation=AuditTrail.UPDATE,
                    module='procurement',
                    entity_type='PurchaseOrder',
                    entity_id=purchase_order.id,
                    user=request.user,
                    reason=f'Purchase order {purchase_order.order_number} marked as received - inventory updated',
                    request=request
                )

                # Send notification about goods received
                send_po_notification(purchase_order, 'received', request.user)

                return APIResponse.success(
                    data=self.get_serializer(purchase_order).data,
                    message='Purchase order marked as received and inventory updated',
                    correlation_id=correlation_id
                )

        except Exception as e:
            logger.error(f'Error marking PO as received: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error marking purchase order as received',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'], url_path='record-payment', name='record_payment')
    def record_payment(self, request, pk=None):
        """
        CRITICAL: Record payment for Purchase Order
        Integrates with Finance module as single source of truth for money-OUT
        """
        try:
            correlation_id = get_correlation_id(request)
            purchase_order = self.get_object()
            
            # Validate input
            amount = request.data.get('amount')
            payment_method = request.data.get('payment_method')
            payment_account_id = request.data.get('payment_account')
            reference = request.data.get('reference')
            payment_date = request.data.get('payment_date')
            notes = request.data.get('notes', '')
            
            if not amount or not payment_method or not payment_account_id:
                return APIResponse.bad_request(
                    message='Amount, payment method, and payment account are required',
                    correlation_id=correlation_id
                )
            
            with transaction.atomic():
                from decimal import Decimal
                amount = Decimal(str(amount))
                
                if amount <= 0:
                    return APIResponse.bad_request(
                        message='Amount must be greater than zero',
                        correlation_id=correlation_id
                    )
                
                if amount > purchase_order.balance_due:
                    return APIResponse.bad_request(
                        message=f'Amount ({amount}) exceeds balance due ({purchase_order.balance_due})',
                        correlation_id=correlation_id
                    )
                
                # Create payment in Finance module (Money OUT)
                from finance.payment.models import Payment
                from finance.accounts.models import PaymentAccounts
                
                payment_account = PaymentAccounts.objects.get(id=payment_account_id)
                
                payment = Payment.objects.create(
                    payment_type='purchase_order_payment',
                    direction='out',
                    amount=amount,
                    payment_method=payment_method,
                    reference_number=reference or f"PO-PAY-{purchase_order.order_number}-{timezone.now().timestamp()}",
                    payment_date=payment_date or timezone.now(),
                    supplier=purchase_order.supplier,
                    payment_account=payment_account,
                    notes=notes,
                    status='completed',
                    verified_by=request.user,
                    verification_date=timezone.now()
                )
                
                # Create PO Payment link
                po_payment = PurchaseOrderPayment.objects.create(
                    purchase_order=purchase_order,
                    payment=payment,
                    amount=amount,
                    payment_account=payment_account,
                    notes=notes
                )
                
                # Log payment
                AuditTrail.log(
                    operation=AuditTrail.UPDATE,
                    module='procurement',
                    entity_type='PurchaseOrder',
                    entity_id=purchase_order.id,
                    user=request.user,
                    reason=f'Payment of {amount} recorded for PO {purchase_order.order_number}',
                    request=request
                )

                # Send notification about payment
                send_po_notification(purchase_order, 'payment_recorded', request.user, str(amount))

                return APIResponse.success(
                    data={
                        'purchase_order': self.get_serializer(purchase_order).data,
                        'payment': PurchaseOrderPaymentSerializer(po_payment).data
                    },
                    message=f'Payment of {amount} recorded successfully',
                    correlation_id=correlation_id
                )
        
        except Exception as e:
            logger.error(f'Error recording PO payment: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error recording payment',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )
    
    @action(detail=True, methods=['get'], url_path='pdf', name='pdf_stream')
    def pdf_stream(self, request, pk=None):
        """
        Stream the LPO (Purchase Order) as a PDF document
        Returns inline PDF for browser preview or download
        
        Query Parameters:
        - download: 'true' to force download, 'false' (default) for inline preview
        """
        try:
            correlation_id = get_correlation_id(request)
            purchase_order = self.get_object()
            
            # Resolve company info using business/branch so PDFs use real branding
            from finance.utils import resolve_company_info
            branch = getattr(purchase_order, 'branch', None)
            biz = getattr(branch, 'business', None) if branch else None
            company_info = resolve_company_info(biz, branch)
            
            # Generate PDF
            pdf_bytes = generate_lpo_pdf(purchase_order, company_info)
            
            # Determine if download or inline
            download = request.query_params.get('download', 'false').lower() == 'true'
            disposition = 'attachment' if download else 'inline'
            
            # Return PDF as HTTP response
            response = HttpResponse(
                pdf_bytes,
                content_type='application/pdf'
            )
            response['Content-Disposition'] = f'{disposition}; filename="LPO-{purchase_order.order_number}.pdf"'
            response['Cache-Control'] = 'public, max-age=3600'  # Cache for 1 hour
            
            # Log PDF access
            AuditTrail.log(
                operation=AuditTrail.VIEW,
                module='procurement',
                entity_type='PurchaseOrder',
                entity_id=purchase_order.id,
                user=request.user,
                reason=f'Generated PDF for LPO {purchase_order.order_number}',
                request=request
            )
            
            logger.info(f"Generated PDF for LPO {purchase_order.order_number} (correlation_id={correlation_id})")
            return response
            
        except PurchaseOrder.DoesNotExist:
            return HttpResponse(
                'Purchase Order not found',
                status=404,
                content_type='text/plain'
            )
        except Exception as e:
            logger.error(f'Error generating PDF for LPO: {str(e)}', exc_info=True)
            return HttpResponse(
                f'Error generating PDF: {str(e)}',
                status=500,
                content_type='text/plain'
            )


class ProcurementDashboardView(APIView):
    """
    Procurement Dashboard API View
    
    Provides analytics and reporting for procurement operations including:
    - Purchase orders and requisitions
    - Supplier performance metrics
    - Spend analysis and trends
    - Category breakdowns
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get procurement dashboard data."""
        try:
            from procurement.analytics.procurement_analytics import ProcurementAnalyticsService
            
            # Get period from query params
            period = request.query_params.get('period', 'month')
            
            # Get dashboard data
            analytics_service = ProcurementAnalyticsService()
            dashboard_data = analytics_service.get_procurement_dashboard_data(period)
            
            return Response({
                'success': True,
                'data': dashboard_data,
                'period': period,
                'generated_at': timezone.now().isoformat()
            })
            
        except ImportError:
            # Return fallback data if analytics service not available
            return Response({
                'success': True,
                'data': {
                    'total_orders': 45,
                    'total_spend': 1250000.0,
                    'pending_orders': 12,
                    'completed_orders': 33,
                    'supplier_count': 25,
                    'average_order_value': 27777.78,
                    'top_suppliers': [
                        {
                            'name': 'ABC Suppliers Ltd',
                            'total_spend': 250000.0,
                            'order_count': 8,
                            'rating': 4.5
                        },
                        {
                            'name': 'XYZ Corporation',
                            'total_spend': 180000.0,
                            'order_count': 6,
                            'rating': 4.2
                        }
                    ],
                    'category_breakdown': [
                        {'category': 'Electronics', 'amount': 450000.0},
                        {'category': 'Office Supplies', 'amount': 280000.0}
                    ],
                    'order_trends': [
                        {'period': 'Jan 01', 'count': 3},
                        {'period': 'Jan 08', 'count': 5}
                    ],
                    'spend_analysis': [
                        {'period': 'Jan 01', 'amount': 45000.0},
                        {'period': 'Jan 08', 'amount': 52000.0}
                    ]
                },
                'period': request.query_params.get('period', 'month'),
                'generated_at': timezone.now().isoformat(),
                'note': 'Using fallback data - analytics service not available'
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
                'generated_at': timezone.now().isoformat()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)