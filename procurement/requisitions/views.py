from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from .models import ProcurementRequest
from .serializers import ProcurementRequestSerializer
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
from core.utils import get_branch_id_from_request, get_business_id_from_request
from business.models import Branch
from approvals.models import Approval, ApprovalWorkflow, ApprovalStep
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


def send_requisition_notification(requisition, notification_type, action_user, additional_message=None):
    """
    Send notification for requisition workflow events.

    Args:
        requisition: The ProcurementRequest instance
        notification_type: Type of notification ('created', 'submitted', 'approved', 'rejected')
        action_user: The user who performed the action
        additional_message: Optional additional context message
    """
    try:
        from notifications.services.notification_service import NotificationService
        from django.contrib.auth import get_user_model
        from approvals.utils import get_approvers_for_permission

        User = get_user_model()
        notification_service = NotificationService()

        # Build base context
        context = {
            'reference_number': requisition.reference_number,
            'request_type': requisition.get_request_type_display() if hasattr(requisition, 'get_request_type_display') else requisition.request_type,
            'purpose': requisition.purpose or 'N/A',
            'requester_name': f"{requisition.requester.first_name} {requisition.requester.last_name}".strip() or requisition.requester.username,
            'action_user_name': f"{action_user.first_name} {action_user.last_name}".strip() or action_user.username,
        }

        if notification_type == 'created':
            # Notify procurement managers/approvers about new requisition
            title = f"New Requisition: {requisition.reference_number}"
            message = f"A new {context['request_type']} requisition has been created by {context['requester_name']}.\n\nPurpose: {context['purpose']}"
            recipients = get_approvers_for_permission('procurement.view_procurementrequest')
            action_url = f"/procurement/requisitions/{requisition.id}"

        elif notification_type == 'submitted':
            # Notify approvers about submitted requisition
            title = f"Requisition Pending Approval: {requisition.reference_number}"
            message = f"A {context['request_type']} requisition has been submitted for approval by {context['requester_name']}.\n\nPurpose: {context['purpose']}"
            recipients = get_approvers_for_permission('procurement.approve_procurementrequest')
            action_url = f"/procurement/requisitions/{requisition.id}"

        elif notification_type == 'approved':
            # Notify requester about approval
            title = f"Requisition Approved: {requisition.reference_number}"
            message = f"Your {context['request_type']} requisition has been approved by {context['action_user_name']}."
            if additional_message:
                message += f"\n\n{additional_message}"
            recipients = [requisition.requester]
            action_url = f"/procurement/requisitions/{requisition.id}"

        elif notification_type == 'rejected':
            # Notify requester about rejection
            title = f"Requisition Rejected: {requisition.reference_number}"
            message = f"Your {context['request_type']} requisition has been rejected by {context['action_user_name']}."
            if additional_message:
                message += f"\n\nReason: {additional_message}"
            recipients = [requisition.requester]
            action_url = f"/procurement/requisitions/{requisition.id}"

        else:
            logger.warning(f"Unknown notification type: {notification_type}")
            return

        # Send notifications to all recipients
        for recipient in recipients:
            if isinstance(recipient, int):
                try:
                    recipient = User.objects.get(id=recipient)
                except User.DoesNotExist:
                    continue

            # Skip sending notification to the user who performed the action
            if recipient.id == action_user.id:
                continue

            try:
                notification_service.send_notification(
                    user=recipient,
                    title=title,
                    message=message,
                    notification_type='APPROVAL',
                    channels=['in_app', 'email'],
                    action_url=action_url,
                    data={
                        'requisition_id': requisition.id,
                        'reference_number': requisition.reference_number,
                        'event_type': notification_type
                    },
                    async_send=False
                )
            except Exception as e:
                logger.error(f"Failed to send notification to {recipient.username}: {str(e)}")

    except ImportError as e:
        logger.warning(f"Notification service not available: {str(e)}")
    except Exception as e:
        logger.error(f"Error sending requisition notification: {str(e)}", exc_info=True)


class ProcurementRequestViewSet(BaseModelViewSet):
    """
    API endpoint that allows procurement requests to be viewed or edited.
    """
    queryset = ProcurementRequest.objects.all()
    serializer_class = ProcurementRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Optimize queries with select_related and prefetch_related for related objects."""
        queryset = ProcurementRequest.objects.all().select_related(
            'requester', 'business', 'branch'
        ).prefetch_related(
            'approvals',
            'approvals__approver',
            'items',
            'items__stock_item',
            'items__supplier',
            'items__provider',
            'preferred_suppliers'
        )

        # Filter by query parameters
        requester = self.request.query_params.get('requester', None)
        status_filter = self.request.query_params.get('status', None)
        request_type = self.request.query_params.get('request_type', None)

        if requester:
            queryset = queryset.filter(requester=requester)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if request_type:
            queryset = queryset.filter(request_type=request_type)

        # Get business and branch context
        business_id = get_business_id_from_request(self.request)
        branch_id = self.request.query_params.get('branch_id') or get_branch_id_from_request(self.request)

        # Filter by business/branch for non-superusers
        if not self.request.user.is_superuser:
            user = self.request.user

            # Get user's associated businesses
            from business.models import Bussiness
            owned_businesses = Bussiness.objects.filter(owner=user)
            employee_businesses = Bussiness.objects.filter(employees__user=user)
            user_businesses = owned_businesses | employee_businesses

            # Filter requisitions by:
            # 1. Requisitions where user is the requester
            # 2. Requisitions in user's businesses
            from django.db.models import Q
            queryset = queryset.filter(
                Q(requester=user) |
                Q(business__in=user_businesses)
            ).distinct()
        else:
            # For superusers, filter by business_id if provided
            if business_id:
                queryset = queryset.filter(business_id=business_id)

        # Additional branch filter if specified
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        return queryset

    def perform_create(self, serializer):
        """Create requisition with requester, business and branch context."""
        # Get business and branch from request context
        business_id = get_business_id_from_request(self.request)
        branch_id = get_branch_id_from_request(self.request)

        # Prepare save kwargs
        save_kwargs = {'requester': self.request.user}

        # Set business from context or user's business
        if business_id:
            from business.models import Bussiness
            try:
                business = Bussiness.objects.get(id=business_id)
                save_kwargs['business'] = business
            except Bussiness.DoesNotExist:
                pass

        # Fallback: Get business from user context
        if 'business' not in save_kwargs:
            from core.utils import get_user_business
            business = get_user_business(self.request.user)
            if business:
                save_kwargs['business'] = business

        # Set branch from context or user's branch
        if branch_id:
            try:
                branch = Branch.objects.get(id=branch_id)
                save_kwargs['branch'] = branch
            except Branch.DoesNotExist:
                pass

        # Fallback: Get branch from user context
        if 'branch' not in save_kwargs:
            from core.utils import get_user_branch
            branch = get_user_branch(self.request.user, self.request)
            if branch:
                save_kwargs['branch'] = branch

        requisition = serializer.save(**save_kwargs)
        # Send notification about new requisition
        send_requisition_notification(requisition, 'created', self.request.user)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a procurement request."""
        try:
            correlation_id = get_correlation_id(request)
            procurement_request = self.get_object()

            # Create approval record using centralized approval system
            content_type = ContentType.objects.get_for_model(procurement_request)

            # Get or create a requisition workflow
            workflow, _ = ApprovalWorkflow.objects.get_or_create(
                workflow_type='requisition',
                defaults={'name': 'Requisition Approval', 'is_active': True}
            )

            # Get or create a default approval step
            step, _ = ApprovalStep.objects.get_or_create(
                workflow=workflow,
                step_number=1,
                defaults={'name': 'Manager Approval', 'approver_type': 'user', 'is_active': True}
            )

            approval = Approval.objects.create(
                content_type=content_type,
                object_id=procurement_request.pk,
                workflow=workflow,
                step=step,
                approver=request.user,
                status='approved',
                approved_at=timezone.now(),
                notes=request.data.get('notes', 'Approved by ' + request.user.username)
            )

            # Add to ManyToMany relationship
            procurement_request.approvals.add(approval)

            # Update request status
            procurement_request.status = 'approved'
            procurement_request.save()

            # Log approval
            AuditTrail.log(
                operation=AuditTrail.APPROVAL,
                module='procurement',
                entity_type='ProcurementRequest',
                entity_id=procurement_request.id,
                user=request.user,
                reason='Procurement request approved',
                request=request
            )

            # Auto-create Purchase Order for external_item requisitions
            purchase_order = None
            if procurement_request.request_type == 'external_item':
                purchase_order = self._create_purchase_order_from_requisition(procurement_request, request.user)

            # Send notification about approval
            additional_msg = 'A Purchase Order has been created.' if purchase_order else None
            send_requisition_notification(procurement_request, 'approved', request.user, additional_msg)

            response_data = self.get_serializer(procurement_request).data
            if purchase_order:
                response_data['purchase_order'] = {
                    'id': purchase_order.id,
                    'order_number': purchase_order.order_number,
                    'status': purchase_order.status
                }

            return APIResponse.success(
                data=response_data,
                message='Procurement request approved successfully' + (' and Purchase Order created' if purchase_order else ''),
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error approving procurement request: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error approving procurement request',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    def _create_purchase_order_from_requisition(self, requisition, user):
        """
        Auto-create a Purchase Order from an approved external_item requisition.
        The PO is created with 'pending_approval' status for further review.
        """
        try:
            from procurement.orders.models import PurchaseOrder
            from core_orders.models import OrderItem

            # Check if a PO already exists for this requisition
            if hasattr(requisition, 'purchase_order') and requisition.purchase_order:
                logger.info(f"Purchase Order already exists for requisition {requisition.id}")
                return requisition.purchase_order

            # Calculate approved budget from requisition items
            total_budget = Decimal('0.00')
            for item in requisition.items.all():
                unit_price = Decimal('0.00')
                if item.stock_item:
                    unit_price = item.stock_item.buying_price or Decimal('0.00')
                elif item.estimated_price:
                    # For external items, use the estimated_price from the requisition
                    unit_price = Decimal(str(item.estimated_price))
                total_budget += unit_price * item.quantity

            # Get branch from requisition items or user
            branch = None
            first_item = requisition.items.first()
            if first_item and first_item.stock_item:
                branch = first_item.stock_item.branch

            # Create the Purchase Order
            purchase_order = PurchaseOrder.objects.create(
                requisition=requisition,
                branch=branch,
                supplier=None,  # To be selected by procurement officer
                status='pending_approval',  # Requires further approval
                approved_budget=total_budget,
                terms='Net 30 days payment terms. Delivery must be completed by specified date.',
                delivery_instructions=f'Delivery Expected as per requisition {requisition.reference_number}',
                expected_delivery=requisition.required_by_date,
                notes=f'Auto-generated from approved requisition {requisition.reference_number}',
                created_by=user
            )

            # Copy items from requisition to PO
            for req_item in requisition.items.all():
                unit_price = Decimal('0.00')
                product = None

                if req_item.stock_item:
                    unit_price = req_item.stock_item.buying_price or Decimal('0.00')
                    product = req_item.stock_item.product
                elif req_item.estimated_price:
                    # For external items, use the estimated_price from the requisition
                    unit_price = Decimal(str(req_item.estimated_price))

                OrderItem.objects.create(
                    order=purchase_order,
                    product=product,
                    stock_item=req_item.stock_item,
                    quantity=req_item.quantity,
                    unit_price=unit_price,
                    description=req_item.description or '',
                    notes=f'From requisition item {req_item.id}'
                )

            # Log the auto-creation
            AuditTrail.log(
                operation=AuditTrail.CREATE,
                module='procurement',
                entity_type='PurchaseOrder',
                entity_id=purchase_order.id,
                user=user,
                reason=f'Auto-created from approved requisition {requisition.reference_number}',
                request=None
            )

            logger.info(f"Auto-created Purchase Order {purchase_order.order_number} from requisition {requisition.reference_number}")
            return purchase_order

        except Exception as e:
            logger.error(f"Error auto-creating Purchase Order from requisition {requisition.id}: {str(e)}", exc_info=True)
            # Don't fail the approval if PO creation fails
            return None
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish a procurement request for approval workflow."""
        try:
            correlation_id = get_correlation_id(request)
            procurement_request = self.get_object()

            # Create approval record using centralized approval system
            content_type = ContentType.objects.get_for_model(procurement_request)

            # Get or create a requisition workflow
            workflow, _ = ApprovalWorkflow.objects.get_or_create(
                workflow_type='requisition',
                defaults={'name': 'Requisition Approval', 'is_active': True}
            )

            # Get or create a default approval step
            step, _ = ApprovalStep.objects.get_or_create(
                workflow=workflow,
                step_number=1,
                defaults={'name': 'Manager Approval', 'approver_type': 'user', 'is_active': True}
            )

            approval = Approval.objects.create(
                content_type=content_type,
                object_id=procurement_request.pk,
                workflow=workflow,
                step=step,
                approver=request.user,
                status='pending',
                notes=request.data.get('notes', 'Published by ' + request.user.username)
            )

            # Add to ManyToMany relationship
            procurement_request.approvals.add(approval)

            # Update request status
            procurement_request.status = 'submitted'
            procurement_request.save()

            # Log publication
            AuditTrail.log(
                operation=AuditTrail.SUBMIT,
                module='procurement',
                entity_type='ProcurementRequest',
                entity_id=procurement_request.id,
                user=request.user,
                reason='Procurement request published',
                request=request
            )

            # Send notification about submission
            send_requisition_notification(procurement_request, 'submitted', request.user)

            return APIResponse.success(
                data=self.get_serializer(procurement_request).data,
                message='Procurement request published successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error publishing procurement request: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error publishing procurement request',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a procurement request."""
        try:
            correlation_id = get_correlation_id(request)
            procurement_request = self.get_object()

            # Create rejection record using centralized approval system
            content_type = ContentType.objects.get_for_model(procurement_request)

            # Get or create a requisition workflow
            workflow, _ = ApprovalWorkflow.objects.get_or_create(
                workflow_type='requisition',
                defaults={'name': 'Requisition Approval', 'is_active': True}
            )

            # Get or create a default approval step
            step, _ = ApprovalStep.objects.get_or_create(
                workflow=workflow,
                step_number=1,
                defaults={'name': 'Manager Approval', 'approver_type': 'user', 'is_active': True}
            )

            approval = Approval.objects.create(
                content_type=content_type,
                object_id=procurement_request.pk,
                workflow=workflow,
                step=step,
                approver=request.user,
                status='rejected',
                rejected_at=timezone.now(),
                notes=request.data.get('notes', 'Rejected by ' + request.user.username)
            )

            # Add to ManyToMany relationship
            procurement_request.approvals.add(approval)

            # Update request status
            procurement_request.status = 'rejected'
            procurement_request.save()

            # Log rejection
            AuditTrail.log(
                operation=AuditTrail.CANCEL,
                module='procurement',
                entity_type='ProcurementRequest',
                entity_id=procurement_request.id,
                user=request.user,
                reason='Procurement request rejected',
                request=request
            )

            # Send notification about rejection
            rejection_notes = request.data.get('notes', '')
            send_requisition_notification(procurement_request, 'rejected', request.user, rejection_notes)

            return APIResponse.success(
                data=self.get_serializer(procurement_request).data,
                message='Procurement request rejected',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error rejecting procurement request: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error rejecting procurement request',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        """
        Process approved requests based on their type
        """
        procurement_request = self.get_object()
        
        if procurement_request.status != 'approved':
            return Response(
                {'error': 'Only approved requests can be processed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Add processing logic here based on request_type
        procurement_request.status = 'processing'
        procurement_request.save()
        return Response({'status': 'processing'})

class UserRequestViewSet(viewsets.ModelViewSet):
    """
    API endpoint that shows requests for the current user only
    """
    serializer_class = ProcurementRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ProcurementRequest.objects.filter(
            requester=self.request.user
        ).select_related(
            'requester', 'business', 'branch'
        ).prefetch_related(
            'approvals', 'items', 'preferred_suppliers'
        )

    def perform_create(self, serializer):
        """Create requisition with requester, business and branch context."""
        # Get business and branch from request context
        business_id = get_business_id_from_request(self.request)
        branch_id = get_branch_id_from_request(self.request)

        save_kwargs = {'requester': self.request.user}

        # Set business from context or user's business
        if business_id:
            from business.models import Bussiness
            try:
                business = Bussiness.objects.get(id=business_id)
                save_kwargs['business'] = business
            except Bussiness.DoesNotExist:
                pass

        if 'business' not in save_kwargs:
            from core.utils import get_user_business
            business = get_user_business(self.request.user)
            if business:
                save_kwargs['business'] = business

        # Set branch from context or user's branch
        if branch_id:
            try:
                branch = Branch.objects.get(id=branch_id)
                save_kwargs['branch'] = branch
            except Branch.DoesNotExist:
                pass

        if 'branch' not in save_kwargs:
            from core.utils import get_user_branch
            branch = get_user_branch(self.request.user, self.request)
            if branch:
                save_kwargs['branch'] = branch

        serializer.save(**save_kwargs)
