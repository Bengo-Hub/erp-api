from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from django.db import transaction
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
        return queryset.select_related('category', 'branch', 'expense_for_user', 'expense_for_contact')

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
    
    @action(detail=True, methods=['get'], url_path='download-pdf', name='download_pdf')
    def download_pdf(self, request, pk=None):
        """
        Generate and download expense PDF report
        """
        try:
            expense = self.get_object()
            
            # Use the invoice PDF generator for now (can be customized for expenses)
            from finance.invoicing.pdf_generator import generate_invoice_pdf
            
            # Generate PDF
            pdf_buffer = generate_invoice_pdf(expense, document_type='expense')
            
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
