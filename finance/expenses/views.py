from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from django.db import models, transaction
from django.utils import timezone
from django.template.loader import render_to_string
from .models import Expense, ExpenseCategory, ExpensePayment, PaymentAccounts, ExpenseEmailLog
from .serializers import ExpenseSerializer, ExpenseCategorySerializer, PaymentSerializer, PaymentAccountSerializer
from .functions import generate_enxpense_ref
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
from notifications.services import EmailService
import logging

logger = logging.getLogger(__name__)


class ExpenseCategoryViewSet(BaseModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated]


class PaymentAccountViewSet(BaseModelViewSet):
    queryset = PaymentAccounts.objects.all()
    serializer_class = PaymentAccountSerializer
    permission_classes = [IsAuthenticated]


class ExpenseViewSet(BaseModelViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['category', 'branch', 'date_added', 'is_refund', 'is_recurring']
    search_fields = ['reference_no', 'expense_note']
    ordering_fields = ['date_added', 'total_amount']
    ordering = ['-date_added']

    def get_queryset(self):
        """Optimize queries with select_related for foreign keys."""
        queryset = super().get_queryset()
        queryset = queryset.select_related('category', 'branch', 'expense_for_user', 'expense_for_contact')
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

    def create(self, request, *args, **kwargs):
        """Create expense with auto-generated reference number."""
        try:
            correlation_id = self.get_correlation_id()
            
            # Auto-generate reference number
            request.data['reference_no'] = generate_enxpense_ref("EP")
            
            serializer = self.get_serializer(data=request.data)
            
            if not serializer.is_valid():
                return APIResponse.validation_error(
                    message='Validation failed',
                    errors=serializer.errors,
                    correlation_id=correlation_id
                )
            
            instance = serializer.save()
            
            # Log creation
            self.log_operation(
                operation=AuditTrail.CREATE,
                obj=instance,
                reason=f'Created expense {instance.reference_no}'
            )
            
            return APIResponse.created(
                data=self.get_serializer(instance).data,
                message='Expense created successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error creating expense: {str(e)}', exc_info=True)
            correlation_id = self.get_correlation_id()
            return APIResponse.server_error(
                message='Error creating expense',
                error_id=str(e),
                correlation_id=correlation_id
            )
    
    @action(detail=True, methods=['post'], url_path='record-payment', name='record_payment')
    def record_payment(self, request, pk=None):
        """
        CRITICAL: Record payment for Expense
        Integrates with Finance module as single source of truth for money-OUT
        """
        try:
            correlation_id = self.get_correlation_id()
            expense = self.get_object()
            
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
                
                if amount > expense.total_amount:
                    return APIResponse.bad_request(
                        message=f'Amount ({amount}) exceeds expense total ({expense.total_amount})',
                        correlation_id=correlation_id
                    )
                
                # Validate branch if header provided
                try:
                    from core.utils import get_branch_id_from_request
                    header_branch_id = request.query_params.get('branch_id') or get_branch_id_from_request(request)
                except Exception:
                    header_branch_id = None

                if header_branch_id and expense.branch_id and str(expense.branch_id) != str(header_branch_id):
                    return APIResponse.forbidden(message='Expense does not belong to the specified branch', correlation_id=correlation_id)

                # Create payment in Finance module (Money OUT)
                from finance.payment.models import Payment
                payment_account = PaymentAccounts.objects.get(id=payment_account_id)
                
                payment = Payment.objects.create(
                    payment_type='expense_payment',
                    direction='out',
                    amount=amount,
                    payment_method=payment_method,
                    reference_number=reference or f"EXP-PAY-{expense.reference_no}-{timezone.now().timestamp()}",
                    payment_date=payment_date or timezone.now(),
                    supplier=expense.expense_for_contact,  # If expense is for a contact/vendor
                    payment_account=payment_account,
                    notes=notes,
                    status='completed',
                    verified_by=request.user,
                    verification_date=timezone.now()
                )
                
                # Create or update expense payment link
                expense_payment = ExpensePayment.objects.create(
                    expense=expense,
                    payment=payment,
                    payment_account=payment_account,
                    payment_note=notes
                )
                
                # Log payment
                AuditTrail.log(
                    operation=AuditTrail.UPDATE,
                    module='finance',
                    entity_type='Expense',
                    entity_id=expense.id,
                    user=request.user,
                    reason=f'Payment of {amount} recorded for expense {expense.reference_no}',
                    request=request
                )
                
                return APIResponse.success(
                    data={
                        'expense': self.get_serializer(expense).data,
                        'payment': {
                            'id': payment.id,
                            'reference_number': payment.reference_number,
                            'amount': float(amount)
                        }
                    },
                    message=f'Payment of {amount} recorded successfully',
                    correlation_id=correlation_id
                )
        
        except Exception as e:
            logger.error(f'Error recording expense payment: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error recording payment',
                error_id=str(e),
                correlation_id=self.get_correlation_id()
            )
    
    @action(detail=True, methods=['post'], url_path='send', name='send_expense')
    def send_expense(self, request, pk=None):
        """
        Send expense report via email
        """
        try:
            correlation_id = self.get_correlation_id()
            expense = self.get_object()
            
            # Get email details
            email_to = request.data.get('email_to')
            send_copy_to = request.data.get('send_copy_to', [])
            message = request.data.get('message', '')
            
            if not email_to:
                # Try to get email from expense_for_user or expense_for_contact
                if expense.expense_for_user and expense.expense_for_user.email:
                    email_to = expense.expense_for_user.email
                elif expense.expense_for_contact and expense.expense_for_contact.user and expense.expense_for_contact.user.email:
                    email_to = expense.expense_for_contact.user.email
                else:
                    return APIResponse.bad_request(
                        message='Recipient email is required',
                        correlation_id=correlation_id
                    )
            
            # Prepare email context
            context = {
                'expense': expense,
                'custom_message': message,
                'business_name': expense.branch.business.name if expense.branch else 'BengoERP',
                'business_email': expense.branch.business.email if expense.branch else '',
                'currency_symbol': 'KES ',
                'recipient_name': expense.expense_for_user.get_full_name() if expense.expense_for_user else '',
                'view_url': f"{request.build_absolute_uri('/')[:-1]}/finance/expenses/{expense.id}",
            }
            
            # Calculate totals if items exist
            if hasattr(expense, 'items'):
                context['subtotal'] = sum(item.subtotal for item in expense.items.all())
                context['tax_amount'] = sum(item.tax_amount for item in expense.items.all())
            
            # Send email using EmailService
            email_service = EmailService()
            email_sent = email_service.send_email(
                subject=f'Expense Report - {expense.reference_no}',
                template_name='notifications/email/expense_report.html',
                context=context,
                recipient_list=[email_to] + send_copy_to,
                from_email=None,  # Use default
                # attachment_path=None  # PDF will be attached if available
            )
            
            if email_sent:
                # Log email
                ExpenseEmailLog.objects.create(
                    expense=expense,
                    email_type='sent',
                    recipient_email=email_to,
                    status='sent'
                )
                
                # Log action
                AuditTrail.log(
                    operation=AuditTrail.UPDATE,
                    module='finance',
                    entity_type='Expense',
                    entity_id=expense.id,
                    user=request.user,
                    reason=f'Expense report {expense.reference_no} sent to {email_to}',
                    request=request
                )
                
                return APIResponse.success(
                    data=self.get_serializer(expense).data,
                    message='Expense report sent successfully',
                    correlation_id=correlation_id
                )
            else:
                return APIResponse.server_error(
                    message='Failed to send expense report',
                    correlation_id=correlation_id
                )
        
        except Exception as e:
            logger.error(f'Error sending expense: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error sending expense report',
                error_id=str(e),
                correlation_id=self.get_correlation_id()
            )
    
    @action(detail=True, methods=['post'], url_path='schedule', name='schedule_expense')
    def schedule_expense(self, request, pk=None):
        """
        Schedule expense report to be sent at a specific time
        """
        try:
            correlation_id = self.get_correlation_id()
            expense = self.get_object()
            
            scheduled_date = request.data.get('scheduled_date')
            message = request.data.get('message', '')
            
            if not scheduled_date:
                return APIResponse.bad_request(
                    message='Scheduled date is required',
                    correlation_id=correlation_id
                )
            
            # TODO: Implement scheduling with Celery Beat
            # For now, just log the request
            logger.info(f'Expense {expense.reference_no} scheduled for {scheduled_date}')
            
            return APIResponse.success(
                data=self.get_serializer(expense).data,
                message=f'Expense report scheduled for {scheduled_date}',
                correlation_id=correlation_id
            )
        
        except Exception as e:
            logger.error(f'Error scheduling expense: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error scheduling expense report',
                error_id=str(e),
                correlation_id=self.get_correlation_id()
            )
    
    @action(detail=True, methods=['post'], url_path='submit-for-approval', name='submit_for_approval')
    def submit_for_approval(self, request, pk=None):
        """
        Submit expense for approval - creates approval request and notifies approvers
        """
        try:
            correlation_id = self.get_correlation_id()
            expense = self.get_object()

            if expense.status != 'draft':
                return APIResponse.bad_request(
                    message='Only draft expenses can be submitted for approval',
                    correlation_id=correlation_id
                )

            with transaction.atomic():
                # Get the expense approval workflow
                from approvals.models import ApprovalWorkflow, ApprovalRequest
                from django.contrib.contenttypes.models import ContentType

                try:
                    workflow = ApprovalWorkflow.objects.get(
                        workflow_type='expense',
                        is_active=True
                    )
                except ApprovalWorkflow.DoesNotExist:
                    # No approval workflow configured - auto-approve to pending
                    expense.status = 'pending'
                    expense.save()

                    return APIResponse.success(
                        data=self.get_serializer(expense).data,
                        message='Expense submitted (no approval workflow configured)',
                        correlation_id=correlation_id
                    )

                # Create approval request
                content_type = ContentType.objects.get_for_model(Expense)
                approval_request = ApprovalRequest.objects.create(
                    content_type=content_type,
                    object_id=expense.id,
                    workflow=workflow,
                    requester=request.user,
                    title=f'Expense Approval: {expense.reference_no}',
                    description=expense.expense_note or f'Expense {expense.reference_no} requires approval',
                    amount=expense.total_amount,
                    status='draft'
                )

                # Submit the request (this creates approval steps)
                approval_request.submit()

                # Update expense status
                expense.status = 'pending'
                expense.save()

                # Send notification to first approver
                first_approval = approval_request.approvals.filter(status='pending').first()
                if first_approval and first_approval.approver:
                    self._notify_approver(expense, first_approval.approver, approval_request)

                # Log action
                AuditTrail.log(
                    operation=AuditTrail.UPDATE,
                    module='finance',
                    entity_type='Expense',
                    entity_id=expense.id,
                    user=request.user,
                    reason=f'Expense {expense.reference_no} submitted for approval',
                    request=request
                )

                return APIResponse.success(
                    data=self.get_serializer(expense).data,
                    message='Expense submitted for approval',
                    correlation_id=correlation_id
                )

        except Exception as e:
            logger.error(f'Error submitting expense for approval: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error submitting expense for approval',
                error_id=str(e),
                correlation_id=self.get_correlation_id()
            )

    def _notify_approver(self, expense, approver, approval_request):
        """Send notification to approver"""
        try:
            email_service = EmailService()
            context = {
                'approver_name': approver.get_full_name() or approver.email,
                'approval_type': 'Expense',
                'requested_by': expense.created_by.get_full_name() if hasattr(expense, 'created_by') and expense.created_by else 'Unknown',
                'amount': str(expense.total_amount),
                'description': expense.expense_note or f'Expense {expense.reference_no}',
                'requested_date': str(timezone.now().date()),
                'action_url': f'/approvals/{approval_request.id}',
                'workflow_name': approval_request.workflow.name,
            }
            email_service.send_email(
                subject=f'Approval Required: Expense {expense.reference_no}',
                template_name='notifications/email/approval_required.html',
                context=context,
                recipient_list=[approver.email],
            )
        except Exception as e:
            logger.warning(f'Failed to send approval notification: {str(e)}')

    @action(detail=True, methods=['post'], url_path='approve', name='approve_expense')
    def approve(self, request, pk=None):
        """Approve an expense"""
        try:
            correlation_id = self.get_correlation_id()
            expense = self.get_object()

            if expense.status != 'pending':
                return APIResponse.bad_request(
                    message='Only pending expenses can be approved',
                    correlation_id=correlation_id
                )

            notes = request.data.get('notes', '')
            comments = request.data.get('comments', '')

            with transaction.atomic():
                # Check for approval request
                from approvals.models import Approval
                from django.contrib.contenttypes.models import ContentType

                content_type = ContentType.objects.get_for_model(Expense)
                pending_approval = Approval.objects.filter(
                    content_type=content_type,
                    object_id=expense.id,
                    approver=request.user,
                    status='pending'
                ).first()

                if pending_approval:
                    pending_approval.approve(notes=notes, comments=comments)

                    # Check if all approvals are done
                    remaining = Approval.objects.filter(
                        content_type=content_type,
                        object_id=expense.id,
                        status='pending'
                    ).count()

                    if remaining == 0:
                        expense.status = 'approved'
                        expense.save()
                else:
                    # Direct approval without workflow
                    expense.status = 'approved'
                    expense.save()

                AuditTrail.log(
                    operation=AuditTrail.UPDATE,
                    module='finance',
                    entity_type='Expense',
                    entity_id=expense.id,
                    user=request.user,
                    reason=f'Expense {expense.reference_no} approved',
                    request=request
                )

                return APIResponse.success(
                    data=self.get_serializer(expense).data,
                    message='Expense approved successfully',
                    correlation_id=correlation_id
                )

        except Exception as e:
            logger.error(f'Error approving expense: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error approving expense',
                error_id=str(e),
                correlation_id=self.get_correlation_id()
            )

    @action(detail=True, methods=['post'], url_path='reject', name='reject_expense')
    def reject(self, request, pk=None):
        """Reject an expense"""
        try:
            correlation_id = self.get_correlation_id()
            expense = self.get_object()

            if expense.status != 'pending':
                return APIResponse.bad_request(
                    message='Only pending expenses can be rejected',
                    correlation_id=correlation_id
                )

            reason = request.data.get('reason', '')
            if not reason:
                return APIResponse.bad_request(
                    message='Rejection reason is required',
                    correlation_id=correlation_id
                )

            with transaction.atomic():
                # Check for approval request
                from approvals.models import Approval
                from django.contrib.contenttypes.models import ContentType

                content_type = ContentType.objects.get_for_model(Expense)
                pending_approval = Approval.objects.filter(
                    content_type=content_type,
                    object_id=expense.id,
                    approver=request.user,
                    status='pending'
                ).first()

                if pending_approval:
                    pending_approval.reject(notes=reason)

                expense.status = 'rejected'
                expense.save()

                AuditTrail.log(
                    operation=AuditTrail.UPDATE,
                    module='finance',
                    entity_type='Expense',
                    entity_id=expense.id,
                    user=request.user,
                    reason=f'Expense {expense.reference_no} rejected: {reason}',
                    request=request
                )

                return APIResponse.success(
                    data=self.get_serializer(expense).data,
                    message='Expense rejected',
                    correlation_id=correlation_id
                )

        except Exception as e:
            logger.error(f'Error rejecting expense: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error rejecting expense',
                error_id=str(e),
                correlation_id=self.get_correlation_id()
            )

    @action(detail=False, methods=['post'], url_path='bulk-approve', name='bulk_approve')
    def bulk_approve(self, request):
        """Bulk approve expenses"""
        try:
            correlation_id = self.get_correlation_id()
            ids = request.data.get('ids', [])

            if not ids:
                return APIResponse.bad_request(
                    message='No expense IDs provided',
                    correlation_id=correlation_id
                )

            with transaction.atomic():
                expenses = Expense.objects.filter(id__in=ids, status='pending')
                count = expenses.update(status='approved')

                return APIResponse.success(
                    data={'approved_count': count},
                    message=f'{count} expense(s) approved',
                    correlation_id=correlation_id
                )

        except Exception as e:
            logger.error(f'Error bulk approving expenses: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error bulk approving expenses',
                error_id=str(e),
                correlation_id=self.get_correlation_id()
            )

    @action(detail=False, methods=['post'], url_path='bulk-reject', name='bulk_reject')
    def bulk_reject(self, request):
        """Bulk reject expenses"""
        try:
            correlation_id = self.get_correlation_id()
            ids = request.data.get('ids', [])
            reason = request.data.get('reason', 'Bulk rejection')

            if not ids:
                return APIResponse.bad_request(
                    message='No expense IDs provided',
                    correlation_id=correlation_id
                )

            with transaction.atomic():
                expenses = Expense.objects.filter(id__in=ids, status='pending')
                count = expenses.update(status='rejected')

                return APIResponse.success(
                    data={'rejected_count': count},
                    message=f'{count} expense(s) rejected',
                    correlation_id=correlation_id
                )

        except Exception as e:
            logger.error(f'Error bulk rejecting expenses: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error bulk rejecting expenses',
                error_id=str(e),
                correlation_id=self.get_correlation_id()
            )

    @action(detail=False, methods=['get'], url_path='summary', name='expense_summary')
    def summary(self, request):
        """Get expense summary statistics"""
        try:
            correlation_id = self.get_correlation_id()
            queryset = self.get_queryset()

            from django.db.models import Count, Sum

            summary = queryset.aggregate(
                total_expenses=Count('id'),
                draft=Count('id', filter=models.Q(status='draft')),
                pending=Count('id', filter=models.Q(status='pending')),
                approved=Count('id', filter=models.Q(status='approved')),
                rejected=Count('id', filter=models.Q(status='rejected')),
                paid=Count('id', filter=models.Q(status='paid')),
                total_amount=Sum('total_amount'),
                pending_amount=Sum('total_amount', filter=models.Q(status='pending')),
            )

            # Handle None values
            for key in summary:
                if summary[key] is None:
                    summary[key] = 0

            return APIResponse.success(
                data=summary,
                message='Summary retrieved',
                correlation_id=correlation_id
            )

        except Exception as e:
            logger.error(f'Error getting expense summary: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error getting summary',
                error_id=str(e),
                correlation_id=self.get_correlation_id()
            )

    @action(detail=True, methods=['get'], url_path='download-pdf', name='download_pdf')
    def download_pdf(self, request, pk=None):
        """
        Generate and download expense PDF report
        """
        try:
            expense = self.get_object()
            
            # Use the invoice PDF generator for expenses with company info
            from finance.invoicing.pdf_generator import generate_invoice_pdf
            from finance.utils import resolve_company_info
            
            # Resolve company info for the expense
            branch = getattr(expense, 'branch', None)
            biz = getattr(branch, 'business', None) if branch else None
            company_info = resolve_company_info(biz, branch)
            
            # Generate PDF
            pdf_buffer = generate_invoice_pdf(expense, company_info, document_type='expense')
            
            # Return PDF response
            response = Response(
                pdf_buffer.getvalue(),
                content_type='application/pdf',
                status=status.HTTP_200_OK
            )
            response['Content-Disposition'] = f'attachment; filename="expense-{expense.reference_no}.pdf"'
            
            return response
        
        except Exception as e:
            logger.error(f'Error generating expense PDF: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error generating PDF',
                error_id=str(e),
                correlation_id=self.get_correlation_id()
            )


class PaymentViewSet(BaseModelViewSet):
    queryset = ExpensePayment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Optimize queries with select_related for foreign keys."""
        queryset = super().get_queryset()
        return queryset.select_related('expense', 'payment_account')
