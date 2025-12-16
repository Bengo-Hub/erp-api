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
        # Use a compact serializer for list/retrieve used by frontend
        if self.action in ['list', 'retrieve']:
            from .serializers import InvoiceFrontendSerializer
            return InvoiceFrontendSerializer
        return InvoiceSerializer

    def _resolve_company_info(self, invoice):
        """Return company info dict including logo_path (filesystem path if possible)"""
        import os
        from django.contrib.staticfiles import finders
        from django.conf import settings

        company_info = None
        if invoice.branch and getattr(invoice.branch, 'business', None):
            biz = invoice.branch.business
            logo_path = None
            try:
                if getattr(biz, 'logo') and hasattr(biz.logo, 'path'):
                    logo_path = biz.logo.path
            except Exception:
                logo_path = None

            # Try staticfiles finders for default logo if not set
            if not logo_path:
                try:
                    default_logo = finders.find('logo/logo.png') or finders.find('static/logo/logo.png')
                    if default_logo:
                        logo_path = default_logo
                    else:
                        possible = os.path.join(getattr(settings, 'BASE_DIR', ''), 'static', 'logo', 'logo.png')
                        logo_path = possible if os.path.exists(possible) else None
                except Exception:
                    possible = os.path.join(getattr(settings, 'BASE_DIR', ''), 'static', 'logo', 'logo.png')
                    logo_path = possible if os.path.exists(possible) else None

            # Prefer contact details from the branch (if available) falling back to business-level fields
            branch = getattr(invoice, 'branch', None)
            # If branch is not set on the invoice, try to find the main HQ branch for the business
            if not branch:
                try:
                    branch = biz.branches.filter(is_main_branch=True, is_active=True).first()
                except Exception:
                    branch = None

            email = ''
            phone = ''
            address = ''
            if branch:
                email = getattr(branch, 'email', '') or getattr(biz, 'email', '') or ''
                phone = getattr(branch, 'contact_number', '') or getattr(biz, 'contact_number', '') or ''
                loc = getattr(branch, 'location', None)
                if loc:
                    from finance.utils import format_location_address
                    address = format_location_address(loc)

            # If still no address from branch, fall back to business.location
            if not address:
                loc = getattr(biz, 'location', None)
                if loc:
                    from finance.utils import format_location_address
                    address = format_location_address(loc)

                    raw_parts = [getattr(loc, 'building_name', None), getattr(loc, 'street_name', None), getattr(loc, 'city', None), getattr(loc, 'county', None), getattr(loc, 'state', None), getattr(loc, 'country', None)]
                    seen = set()
                    cleaned = []
                    for p in raw_parts:
                        v = _part_val(p).strip()
                        if not v:
                            continue
                        key = v.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        cleaned.append(v)
                    address = ', '.join(cleaned)

            # If branch has no contact info, try business-level attributes (older schemas)
            if not email:
                email = getattr(biz, 'email', '') if hasattr(biz, 'email') else ''
            if not phone:
                phone = getattr(biz, 'contact_number', '') if hasattr(biz, 'contact_number') else ''

            company_info = {
                'name': getattr(biz, 'name', 'Company Name'),
                'address': address or (getattr(biz, 'address', '') if hasattr(biz, 'address') else ''),
                'email': email,
                'phone': phone,
                'logo_path': logo_path
            }

        # If still no company_info, try to resolve default static logo
        if not company_info:
            company_info = {}
            try:
                default_logo = finders.find('logo/logo.png') or finders.find('static/logo/logo.png')
                if default_logo:
                    company_info['logo_path'] = default_logo
            except Exception:
                # best effort fallback
                candidate = os.path.join(getattr(settings, 'BASE_DIR', ''), 'static', 'logo', 'logo.png')
                if os.path.exists(candidate):
                    company_info['logo_path'] = candidate

        return company_info

    def create(self, request, *args, **kwargs):
        """Create invoice and return invoice data plus generated PDF (base64) for immediate preview"""
        try:
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return APIResponse.validation_error(message='Validation failed', errors=serializer.errors)

            # Save invoice with created_by set
            invoice = serializer.save(created_by=request.user)

            # Resolve company info and logo path (if available)
            company_info = self._resolve_company_info(invoice)

            # Generate PDF (support alternate document types via ?type=packing_slip|delivery_note)
            doc_type = request.query_params.get('type', 'invoice')
            pdf_bytes = generate_invoice_pdf(invoice, company_info, document_type=doc_type)

            # Decide whether to stream PDF back directly or return JSON with a download url
            accept_header = request.META.get('HTTP_ACCEPT', '')
            stream_param = str(request.query_params.get('stream_pdf', '')).lower()
            stream_pdf = ('application/pdf' in accept_header) or (stream_param in ['1', 'true', 'yes'])

            if stream_pdf:
                # Return PDF stream directly (frontend will convert to blob)
                response = HttpResponse(pdf_bytes, content_type='application/pdf')
                response['Content-Disposition'] = f'inline; filename="Invoice_{invoice.invoice_number}.pdf"'
                # Location header points to the created invoice resource
                response['Location'] = request.build_absolute_uri(f'/finance/invoices/{invoice.id}/')
                response.status_code = 201
                return response

            # Otherwise return JSON with invoice data and pdf_url for later download
            data = InvoiceSerializer(invoice).data
            data.update({'pdf_url': request.build_absolute_uri(f'/finance/invoices/{invoice.id}/pdf')})

            # Log creation
            self.log_operation(operation='CREATE', obj=invoice, reason=f'Created new Invoice')

            return APIResponse.created(data=data, message=f'Invoice created successfully', correlation_id=self.get_correlation_id())

        except Exception as e:
            return APIResponse.server_error(message='Error creating Invoice', error_id=str(e))
    
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
        
        # Only sent/overdue invoices can be sent; draft invoices must be approved first
        if invoice.status == 'draft':
            return APIResponse.error(
                error_code='INVOICE_IN_DRAFT',
                message='Cannot send draft invoices. Invoice must be approved first.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
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
                'address': getattr(company, 'address', '') if company else '',
                'email': getattr(company, 'email', '') if company else '',
                'phone': getattr(company, 'contact_number', '') if company else '',
            } if company else None

            # Prefer branch-level contact details (branch stores email/contact_number)
            if getattr(invoice, 'branch', None):
                branch = invoice.branch
                if branch.email:
                    company_info['email'] = branch.email
                if getattr(branch, 'contact_number', None):
                    company_info['phone'] = branch.contact_number
            
            doc_type = request.query_params.get('type', 'invoice')
            pdf_bytes = generate_invoice_pdf(invoice, company_info, document_type=doc_type)
            
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
            return APIResponse.error(
                error_code='INVOICE_SEND_FAILED',
                message=f'Failed to send invoice: {str(e)}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
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
    
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """
        Approve invoice - change status from draft to sent
        """
        invoice = self.get_object()
        
        # Only draft invoices can be approved
        if invoice.status != 'draft':
            return APIResponse.error(
                error_code='INVOICE_NOT_DRAFT',
                message=f'Only draft invoices can be approved. Current status: {invoice.get_status_display()}',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Change status from draft to sent
            invoice.status = 'sent'
            # If the invoice requires approval, mark it approved and record approver info
            if getattr(invoice, 'requires_approval', False):
                invoice.approval_status = 'approved'
                invoice.approved_by = request.user
                invoice.approved_at = timezone.now()
            invoice.save(update_fields=['status', 'approval_status', 'approved_by', 'approved_at'])
            
            return APIResponse.success(
                data=InvoiceSerializer(invoice).data,
                message=f'Invoice {invoice.invoice_number} approved successfully'
            )
        except Exception as e:
            return APIResponse.error(
                error_code='INVOICE_APPROVAL_FAILED',
                message=f'Failed to approve invoice: {str(e)}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
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
            from django.db import transaction
            from finance.accounts.models import PaymentAccounts

            amount = Decimal(str(amount))
            
            if amount <= 0:
                return APIResponse.bad_request(message='Amount must be greater than zero')
            
            if invoice.requires_approval and getattr(invoice, 'approval_status', None) != 'approved':
                return APIResponse.bad_request(message='Invoice must be approved before recording payment')

            if amount > invoice.balance_due:
                return APIResponse.bad_request(
                    message=f'Amount ({amount}) exceeds balance due ({invoice.balance_due})'
                )

            # Normalize payment_date: accept ISO date or datetime strings, or date/datetime objects
            from datetime import datetime, date, time
            parsed_payment_datetime = None
            if payment_date:
                try:
                    # If ISO datetime provided
                    if isinstance(payment_date, str):
                        try:
                            parsed_payment_datetime = datetime.fromisoformat(payment_date)
                        except Exception:
                            # Fallback: parse date-only string
                            parsed_payment_datetime = datetime.combine(date.fromisoformat(payment_date.split('T')[0]), time.min)
                    elif isinstance(payment_date, datetime):
                        parsed_payment_datetime = payment_date
                    elif isinstance(payment_date, date):
                        parsed_payment_datetime = datetime.combine(payment_date, time.min)
                except Exception:
                    parsed_payment_datetime = timezone.now()
            else:
                parsed_payment_datetime = timezone.now()

            # Ensure timezone-aware datetime
            if timezone.is_naive(parsed_payment_datetime):
                parsed_payment_datetime = timezone.make_aware(parsed_payment_datetime, timezone.get_current_timezone())

            with transaction.atomic():
                # Validate payment account
                try:
                    payment_account = PaymentAccounts.objects.get(id=payment_account_id)
                except PaymentAccounts.DoesNotExist:
                    return APIResponse.not_found(message='Payment account not found')
                
                # Create payment and link (pass the payment account so Payment.payment_account is set)
                payment = invoice.record_payment(
                    amount=amount,
                    payment_method=payment_method,
                    reference=reference,
                    payment_date=parsed_payment_datetime,
                    payment_account=payment_account
                )

                invoice_payment = InvoicePayment.objects.create(
                    invoice=invoice,
                    payment=payment,
                    amount=amount,
                    payment_account=payment_account,
                    payment_date=parsed_payment_datetime.date(),
                    notes=notes
                )
                # Ensure invoice totals and status are recalculated and persisted
                try:
                    invoice.recalculate_payments(user=request.user)
                    invoice.refresh_from_db()
                except Exception:
                    invoice.refresh_from_db()
            
            # Return invoice and created invoice payment details to help frontend link the records
            # Audit log the payment operation
            try:
                from core.audit import AuditTrail
                AuditTrail.log(
                    operation=AuditTrail.PAYMENT,
                    module='finance',
                    entity_type='Invoice',
                    entity_id=invoice.id,
                    user=request.user,
                    changes={'payment_amount': {'new': str(amount)}, 'payment_account': {'new': getattr(payment_account, 'id', None)}},
                    reason=f'Recorded payment {amount} on invoice {invoice.invoice_number} via {payment_method}'
                )
            except Exception:
                pass
            return APIResponse.success(
                data={
                    'invoice': InvoiceSerializer(invoice).data,
                    'invoice_payment': InvoicePaymentSerializer(invoice_payment).data
                },
                message=f'Payment of {amount} recorded successfully'
            )
        
        except Exception as e:
            return APIResponse.error(
                error_code='INVOICE_PAYMENT_FAILED',
                message=str(e),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
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
    
    @action(detail=True, methods=['post'], url_path='generate-share-link')
    def generate_share_link(self, request, pk=None):
        """
        Generate a public shareable link for the invoice
        """
        invoice = self.get_object()
        
        try:
            # Generate share token if not exists
            token = invoice.generate_share_token()
            public_url = invoice.get_public_share_url(request)
            
            # Update allow_public_payment flag
            allow_payment = request.data.get('allow_payment', False)
            if allow_payment:
                invoice.allow_public_payment = True
                invoice.save(update_fields=['allow_public_payment'])
            
            return APIResponse.success(
                data={
                    'id': invoice.id,
                    'url': public_url,
                    'token': token,
                    'is_shared': invoice.is_shared,
                    'allow_payment': invoice.allow_public_payment
                },
                message='Share link generated successfully'
            )
        except Exception as e:
            return APIResponse.error(
                error_code='SHARE_LINK_ERROR',
                message=f'Failed to generate share link: {str(e)}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], url_path='send-whatsapp')
    def send_whatsapp(self, request, pk=None):
        """
        Send invoice via WhatsApp with public view link
        """
        invoice = self.get_object()
        
        try:
            phone = request.data.get('phone')
            message = request.data.get('message', f'Check this invoice: {invoice.invoice_number}')
            
            if not phone:
                return APIResponse.bad_request(
                    message='Phone number is required'
                )
            
            # Generate share link if needed
            if not invoice.share_token:
                invoice.generate_share_token()
            
            public_url = invoice.get_public_share_url(request)
            
            # Log WhatsApp send
            InvoiceEmailLog.objects.create(
                invoice=invoice,
                email_type='whatsapp',
                recipient_email=phone,
                status='sent'
            )
            
            return APIResponse.success(
                data={
                    'invoice_id': invoice.id,
                    'phone': phone,
                    'public_url': public_url
                },
                message='WhatsApp message ready to send (open WhatsApp Web on client)'
            )
        except Exception as e:
            return APIResponse.error(
                error_code='WHATSAPP_ERROR',
                message=f'Failed to send via WhatsApp: {str(e)}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
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
            # Ensure invoice totals/status are up-to-date before rendering PDF
            try:
                invoice.recalculate_payments()
            except Exception:
                pass
            
            # Resolve company info (including logo) for PDF
            company_info = self._resolve_company_info(invoice)
            
            # Generate PDF
            doc_type = request.query_params.get('type', 'invoice')
            pdf_bytes = generate_invoice_pdf(invoice, company_info, document_type=doc_type)
            
            # Return as downloadable file
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="Invoice_{invoice.invoice_number}.pdf"'
            return response
            
        except Exception as e:
            return APIResponse.error(message=str(e))
    
    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf_stream(self, request, pk=None):
        """
        Stream invoice as PDF for inline preview or download
        Query Parameters:
        - download: 'true' to force download, 'false' (default) for inline preview
        """
        try:
            invoice = self.get_object()

            # Ensure latest payment state and DB state before rendering PDF
            try:
                invoice.recalculate_payments()
            except Exception:
                pass

            # Refresh from DB to make sure totals updated via related-model updates
            try:
                invoice.refresh_from_db()
            except Exception:
                pass
            
            # Resolve company info (including logo) for PDF
            company_info = self._resolve_company_info(invoice)
            
            # Generate PDF
            pdf_bytes = generate_invoice_pdf(invoice, company_info)
            
            # Determine if download or inline
            download = request.query_params.get('download', 'false').lower() == 'true'
            disposition = 'attachment' if download else 'inline'
            
            # Return PDF as HTTP response
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'{disposition}; filename="Invoice_{invoice.invoice_number}.pdf"'
            # Prevent clients from using stale cached PDF - always revalidate
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'

            # Compute an aggregate 'last modified' considering related items and payments
            from django.db.models import Max
            last_candidates = []
            lm_invoice = getattr(invoice, 'updated_at', None) or getattr(invoice, 'created_at', None)
            if lm_invoice:
                last_candidates.append(lm_invoice)

            items_lm = invoice.items.aggregate(max_updated=Max('updated_at'))['max_updated']
            if items_lm:
                last_candidates.append(items_lm)

            payments_lm = invoice.invoice_payments.aggregate(max_created=Max('created_at'))['max_created']
            if payments_lm:
                last_candidates.append(payments_lm)

            # Choose most recent timestamp
            last_modified = max(last_candidates) if last_candidates else None

            if last_modified:
                from django.utils.http import http_date
                response['Last-Modified'] = http_date(last_modified.timestamp())

            try:
                import hashlib
                etag_src = f"{invoice.pk}-{getattr(last_modified, 'isoformat', lambda: '')()}-{getattr(invoice, 'total', '')}-{invoice.items.count()}"
                etag = hashlib.sha1(etag_src.encode()).hexdigest()
                response['ETag'] = f'W/"{etag}"'
            except Exception:
                pass

            # Honor conditional requests
            from django.http import HttpResponseNotModified
            if_none_match = request.META.get('HTTP_IF_NONE_MATCH') or request.headers.get('If-None-Match')
            if if_none_match and response.get('ETag') and if_none_match == response['ETag']:
                return HttpResponseNotModified()

            if_modified_since = request.META.get('HTTP_IF_MODIFIED_SINCE') or request.headers.get('If-Modified-Since')
            if if_modified_since and last_modified:
                from django.utils.http import parse_http_date_safe
                client_ts = parse_http_date_safe(if_modified_since)
                if client_ts and int(last_modified.timestamp()) <= client_ts:
                    return HttpResponseNotModified()

            return response
            
        except Invoice.DoesNotExist:
            return HttpResponse('Invoice not found', status=404, content_type='text/plain')
        except Exception as e:
            return HttpResponse(f'Error generating PDF: {str(e)}', status=500, content_type='text/plain')
    
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


# Public API Views (No Authentication Required)
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny


class PublicInvoiceView(APIView):
    """
    Public API endpoint for viewing invoices via share token
    Allows unauthenticated access to shared invoices
    """
    permission_classes = [AllowAny]
    
    def get(self, request, invoice_id, token):
        """Retrieve invoice by ID and share token"""
        try:
            invoice = Invoice.objects.get(id=invoice_id, share_token=token, is_shared=True)
            
            # Mark as viewed if customer is viewing
            invoice.mark_as_viewed()
            
            # Return invoice data
            serializer = InvoiceSerializer(invoice)
            return APIResponse.success(
                data=serializer.data,
                message='Invoice retrieved successfully'
            )
        except Invoice.DoesNotExist:
            return APIResponse.error(
                error_code='INVOICE_NOT_FOUND',
                message='Invoice not found or access denied',
                status_code=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return APIResponse.error(
                error_code='PUBLIC_INVOICE_ERROR',
                message=f'Error accessing invoice: {str(e)}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

