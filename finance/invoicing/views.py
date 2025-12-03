from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Q, Sum
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse
from .models import Invoice, InvoicePayment, InvoiceEmailLog
from .serializers import (
    InvoiceSerializer, InvoiceCreateSerializer, InvoiceSendSerializer,
    InvoiceScheduleSerializer, InvoicePaymentSerializer, InvoiceEmailLogSerializer
)
from .pdf_generator import generate_invoice_pdf


class InvoiceViewSet(BaseModelViewSet):
    """
    Comprehensive Invoice ViewSet with Zoho-like functionality
    """
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['status', 'customer', 'invoice_date', 'due_date', 'payment_status']
    search_fields = ['invoice_number', 'customer__user__first_name', 'customer__user__last_name', 'customer__business_name']
    ordering_fields = ['invoice_date', 'due_date', 'total', 'created_at']
    ordering = ['-invoice_date']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return InvoiceCreateSerializer
        return InvoiceSerializer
    
    def get_queryset(self):
        """Filter invoices based on user organization"""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter by organization (if user is not superuser)
        if not user.is_superuser:
            queryset = queryset.filter(
                Q(branch__business__owner=user) | 
                Q(branch__business__employees__user=user) |
                Q(created_by=user)
            ).distinct()
        
        # Filter by status
        status_filter = self.request.query_params.get('status_filter', None)
        if status_filter == 'draft':
            queryset = queryset.filter(status='draft')
        elif status_filter == 'sent':
            queryset = queryset.filter(status='sent')
        elif status_filter == 'overdue':
            queryset = queryset.filter(status='overdue')
        elif status_filter == 'paid':
            queryset = queryset.filter(status='paid')
        elif status_filter == 'unpaid':
            queryset = queryset.exclude(status__in=['paid', 'cancelled', 'void'])
        
        return queryset
    
    @action(detail=True, methods=['post'], url_path='send')
    def send_invoice(self, request, pk=None):
        """
        Send invoice to customer via email (Zoho-like functionality)
        """
        invoice = self.get_object()
        serializer = InvoiceSendSerializer(data=request.data)
        
        if not serializer.is_valid():
            return APIResponse.bad_request(
                message='Invalid data',
                errors=serializer.errors
            )
        
        # Get email details
        email_to = serializer.validated_data.get('email_to', invoice.customer.user.email)
        send_copy_to = serializer.validated_data.get('send_copy_to', [])
        custom_message = serializer.validated_data.get('message', '')
        
        try:
            # Prepare email context
            from notifications.services.email_service import EmailService
            from business.models import Bussiness
            
            # Get company info
            company = None
            if invoice.branch:
                company = invoice.branch.business if hasattr(invoice.branch, 'business') else Bussiness.objects.first()
            else:
                company = Bussiness.objects.first()
            
            context = {
                'customer_name': invoice.customer.business_name or f"{invoice.customer.user.first_name} {invoice.customer.user.last_name}".strip(),
                'invoice_number': invoice.invoice_number,
                'invoice_date': invoice.invoice_date.strftime('%d/%m/%Y'),
                'due_date': invoice.due_date.strftime('%d/%m/%Y'),
                'payment_terms': invoice.get_payment_terms_display(),
                'total_amount': f"{invoice.total:,.2f}",
                'customer_notes': custom_message or invoice.customer_notes,
                'invoice_url': f"{request.build_absolute_uri('/')[:-1]}/finance/invoices/{invoice.id}",
                'company_name': company.name if company else 'Company',
                'year': timezone.now().year
            }
            
            # Generate PDF attachment
            from .pdf_generator import generate_invoice_pdf
            company_info = {
                'name': company.name if company else 'Company',
                'address': company.address if company else '',
                'email': company.email if company else '',
                'phone': company.contact_number if company else '',
            } if company else None
            
            pdf_bytes = generate_invoice_pdf(invoice, company_info)
            
            # Send email with PDF attachment
            email_service = EmailService()
            email_service.send_django_template_email(
                template_name='notifications/email/invoice_sent.html',
                context=context,
                subject=f'Invoice {invoice.invoice_number} from {company.name if company else "Company"}',
                recipient_list=[email_to],
                cc=send_copy_to if send_copy_to else None,
                attachments=[
                    (f'Invoice_{invoice.invoice_number}.pdf', pdf_bytes, 'application/pdf')
                ],
                async_send=True
            )
            
            # Mark as sent
            invoice.mark_as_sent(user=request.user)
            
            # Log email
            InvoiceEmailLog.objects.create(
                invoice=invoice,
                email_type='sent',
                recipient_email=email_to,
                status='sent'
            )
            
            return APIResponse.success(
                data=InvoiceSerializer(invoice).data,
                message=f'Invoice {invoice.invoice_number} sent successfully to {email_to}'
            )
            
        except Exception as e:
            return APIResponse.error(message=f'Failed to send invoice: {str(e)}')
    
    @action(detail=True, methods=['post'], url_path='schedule')
    def schedule_invoice(self, request, pk=None):
        """
        Schedule invoice to be sent later (Zoho feature)
        """
        invoice = self.get_object()
        serializer = InvoiceScheduleSerializer(data=request.data)
        
        if not serializer.is_valid():
            return APIResponse.bad_request(
                message='Invalid data',
                errors=serializer.errors
            )
        
        invoice.is_scheduled = True
        invoice.scheduled_send_date = serializer.validated_data['scheduled_date']
        invoice.save(update_fields=['is_scheduled', 'scheduled_send_date'])
        
        return APIResponse.success(
            data=InvoiceSerializer(invoice).data,
            message=f'Invoice scheduled to be sent on {invoice.scheduled_send_date}'
        )
    
    @action(detail=True, methods=['post'], url_path='mark-as-sent')
    def mark_sent(self, request, pk=None):
        """Mark invoice as sent without actually sending email"""
        invoice = self.get_object()
        invoice.mark_as_sent(user=request.user)
        
        return APIResponse.success(
            data=InvoiceSerializer(invoice).data,
            message='Invoice marked as sent'
        )
    
    @action(detail=True, methods=['post'], url_path='record-payment')
    def record_payment(self, request, pk=None):
        """
        Record a payment against the invoice
        """
        invoice = self.get_object()
        
        amount = request.data.get('amount')
        payment_method = request.data.get('payment_method')
        payment_account_id = request.data.get('payment_account')
        reference = request.data.get('reference')
        payment_date = request.data.get('payment_date')
        notes = request.data.get('notes', '')
        
        if not amount or not payment_method or not payment_account_id:
            return APIResponse.bad_request(
                message='Amount, payment method, and payment account are required'
            )
        
        try:
            from decimal import Decimal
            amount = Decimal(str(amount))
            
            if amount <= 0:
                return APIResponse.bad_request(message='Amount must be greater than zero')
            
            if amount > invoice.balance_due:
                return APIResponse.bad_request(
                    message=f'Amount ({amount}) exceeds balance due ({invoice.balance_due})'
                )
            
            # Create payment
            payment = invoice.record_payment(
                amount=amount,
                payment_method=payment_method,
                reference=reference,
                payment_date=payment_date
            )
            
            # Create invoice payment link
            from finance.accounts.models import PaymentAccounts
            payment_account = PaymentAccounts.objects.get(id=payment_account_id)
            
            InvoicePayment.objects.create(
                invoice=invoice,
                payment=payment,
                amount=amount,
                payment_account=payment_account,
                notes=notes
            )
            
            return APIResponse.success(
                data=InvoiceSerializer(invoice).data,
                message=f'Payment of {amount} recorded successfully'
            )
        
        except Exception as e:
            return APIResponse.error(message=str(e))
    
    @action(detail=True, methods=['post'], url_path='void')
    def void_invoice(self, request, pk=None):
        """Void an invoice"""
        invoice = self.get_object()
        reason = request.data.get('reason', '')
        
        if invoice.status == 'paid':
            return APIResponse.bad_request(
                message='Cannot void a paid invoice. Issue a credit note instead.'
            )
        
        invoice.void_invoice(reason=reason)
        
        return APIResponse.success(
            data=InvoiceSerializer(invoice).data,
            message='Invoice voided successfully'
        )
    
    @action(detail=True, methods=['post'], url_path='clone')
    def clone_invoice(self, request, pk=None):
        """Clone an invoice"""
        invoice = self.get_object()
        
        try:
            cloned_invoice = invoice.clone_invoice()
            return APIResponse.success(
                data=InvoiceSerializer(cloned_invoice).data,
                message=f'Invoice cloned successfully as {cloned_invoice.invoice_number}'
            )
        except Exception as e:
            return APIResponse.error(message=str(e))
    
    @action(detail=True, methods=['post'], url_path='send-reminder')
    def send_reminder(self, request, pk=None):
        """Send payment reminder"""
        invoice = self.get_object()
        
        if invoice.status in ['paid', 'cancelled', 'void']:
            return APIResponse.bad_request(
                message='Cannot send reminder for this invoice status'
            )
        
        invoice.send_reminder()
        
        # Log email
        InvoiceEmailLog.objects.create(
            invoice=invoice,
            email_type='reminder',
            recipient_email=invoice.customer.user.email,
            status='sent'
        )
        
        return APIResponse.success(
            data=InvoiceSerializer(invoice).data,
            message='Reminder sent successfully'
        )
    
    @action(detail=False, methods=['get'], url_path='summary')
    def invoice_summary(self, request):
        """Get invoice summary statistics"""
        queryset = self.get_queryset()
        
        total_invoices = queryset.count()
        draft_count = queryset.filter(status='draft').count()
        sent_count = queryset.filter(status='sent').count()
        paid_count = queryset.filter(status='paid').count()
        overdue_count = queryset.filter(status='overdue').count()
        
        total_amount = queryset.aggregate(Sum('total'))['total__sum'] or 0
        paid_amount = queryset.filter(status='paid').aggregate(Sum('total'))['total__sum'] or 0
        outstanding_amount = queryset.exclude(status__in=['paid', 'cancelled', 'void']).aggregate(Sum('balance_due'))['balance_due__sum'] or 0
        
        data = {
            'total_invoices': total_invoices,
            'draft': draft_count,
            'sent': sent_count,
            'paid': paid_count,
            'overdue': overdue_count,
            'total_amount': float(total_amount),
            'paid_amount': float(paid_amount),
            'outstanding_amount': float(outstanding_amount),
        }
        
        return APIResponse.success(data=data)
    
    @action(detail=True, methods=['get'], url_path='download-pdf')
    def download_pdf(self, request, pk=None):
        """
        Download invoice as PDF
        Professional print-ready invoice document
        """
        try:
            invoice = self.get_object()
            
            # Get company info from branch/business
            company_info = None
            if invoice.branch:
                company_info = {
                    'name': invoice.branch.business.name if hasattr(invoice.branch, 'business') else 'Company Name',
                    'address': getattr(invoice.branch, 'address', ''),
                    'email': getattr(invoice.branch, 'email', ''),
                    'phone': getattr(invoice.branch, 'phone', ''),
                }
            
            # Generate PDF
            pdf_bytes = generate_invoice_pdf(invoice, company_info)
            
            # Return as downloadable file
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="Invoice_{invoice.invoice_number}.pdf"'
            return response
            
        except Exception as e:
            return APIResponse.error(message=str(e))
    
    @action(detail=False, methods=['post'], url_path='bulk-send')
    def bulk_send(self, request):
        """
        Bulk send multiple invoices at once
        """
        invoice_ids = request.data.get('invoice_ids', [])
        
        if not invoice_ids:
            return APIResponse.bad_request(message='No invoices selected')
        
        try:
            invoices = Invoice.objects.filter(id__in=invoice_ids, status='draft')
            
            if not invoices.exists():
                return APIResponse.bad_request(message='No valid draft invoices found')
            
            from notifications.services.email_service import EmailService
            from business.models import Bussiness
            
            company = Bussiness.objects.first()
            email_service = EmailService()
            
            sent_count = 0
            failed_count = 0
            results = []
            
            for invoice in invoices:
                try:
                    email_to = invoice.customer.user.email
                    
                    context = {
                        'customer_name': invoice.customer.business_name or f"{invoice.customer.user.first_name} {invoice.customer.user.last_name}".strip(),
                        'invoice_number': invoice.invoice_number,
                        'invoice_date': invoice.invoice_date.strftime('%d/%m/%Y'),
                        'due_date': invoice.due_date.strftime('%d/%m/%Y'),
                        'payment_terms': invoice.get_payment_terms_display(),
                        'total_amount': f"{invoice.total:,.2f}",
                        'customer_notes': invoice.customer_notes,
                        'invoice_url': f"{request.build_absolute_uri('/')[:-1]}/finance/invoices/{invoice.id}",
                        'company_name': company.name if company else 'Company',
                        'year': timezone.now().year
                    }
                    
                    # Generate PDF
                    from .pdf_generator import generate_invoice_pdf
                    company_info = {
                        'name': company.name if company else 'Company',
                        'address': company.address if company else '',
                        'email': company.email if company else '',
                        'phone': company.contact_number if company else '',
                    } if company else None
                    
                    pdf_bytes = generate_invoice_pdf(invoice, company_info)
                    
                    # Send email
                    email_service.send_django_template_email(
                        template_name='notifications/email/invoice_sent.html',
                        context=context,
                        subject=f'Invoice {invoice.invoice_number} from {company.name if company else "Company"}',
                        recipient_list=[email_to],
                        attachments=[
                            (f'Invoice_{invoice.invoice_number}.pdf', pdf_bytes, 'application/pdf')
                        ],
                        async_send=True
                    )
                    
                    # Mark as sent
                    invoice.mark_as_sent(user=request.user)
                    
                    # Log email
                    InvoiceEmailLog.objects.create(
                        invoice=invoice,
                        email_type='sent',
                        recipient_email=email_to,
                        status='sent'
                    )
                    
                    sent_count += 1
                    results.append({
                        'invoice_number': invoice.invoice_number,
                        'status': 'sent',
                        'recipient': email_to
                    })
                    
                except Exception as e:
                    failed_count += 1
                    results.append({
                        'invoice_number': invoice.invoice_number,
                        'status': 'failed',
                        'error': str(e)
                    })
            
            return APIResponse.success(
                data={
                    'sent': sent_count,
                    'failed': failed_count,
                    'total': sent_count + failed_count,
                    'results': results
                },
                message=f'Bulk send completed: {sent_count} sent, {failed_count} failed'
            )
            
        except Exception as e:
            return APIResponse.error(message=str(e))


class InvoicePaymentViewSet(viewsets.ModelViewSet):
    """Invoice Payment Management"""
    queryset = InvoicePayment.objects.all()
    serializer_class = InvoicePaymentSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['invoice', 'payment_account', 'payment_date']
    ordering = ['-payment_date']


class InvoiceEmailLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Invoice Email Log (Read-only)"""
    queryset = InvoiceEmailLog.objects.all()
    serializer_class = InvoiceEmailLogSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['invoice', 'email_type', 'status']
    ordering = ['-sent_at']
