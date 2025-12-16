from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Q, Sum, Count
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse
from .models import Quotation, QuotationEmailLog
from .serializers import (
    QuotationSerializer, QuotationCreateSerializer, QuotationSendSerializer,
    QuotationConvertSerializer, QuotationEmailLogSerializer
)
from finance.invoicing.pdf_generator import generate_quotation_pdf


class QuotationViewSet(BaseModelViewSet):
    """
    Comprehensive Quotation ViewSet - Quote to Invoice workflow
    """
    queryset = Quotation.objects.all()
    serializer_class = QuotationSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['status', 'customer', 'quotation_date', 'valid_until', 'is_converted']
    search_fields = ['quotation_number', 'customer__user__first_name', 'customer__user__last_name', 'customer__business_name']
    ordering_fields = ['quotation_date', 'valid_until', 'total', 'created_at']
    ordering = ['-quotation_date']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return QuotationCreateSerializer
        return QuotationSerializer
    
    def get_queryset(self):
        """Filter quotations based on user organization"""
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
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by conversion status
        converted_filter = self.request.query_params.get('converted', None)
        if converted_filter == 'true':
            queryset = queryset.filter(is_converted=True)
        elif converted_filter == 'false':
            queryset = queryset.filter(is_converted=False)
        
        return queryset
    
    @action(detail=True, methods=['post'], url_path='send')
    def send_quotation(self, request, pk=None):
        """
        Send quotation to customer via email
        """
        quotation = self.get_object()
        serializer = QuotationSendSerializer(data=request.data)
        
        if not serializer.is_valid():
            return APIResponse.bad_request(
                message='Invalid data',
                errors=serializer.errors
            )
        
        # Get email details
        email_to = serializer.validated_data.get('email_to', quotation.customer.user.email)
        send_copy_to = serializer.validated_data.get('send_copy_to', [])
        custom_message = serializer.validated_data.get('message', '')
        
        try:
            # Prepare email context
            from notifications.services.email_service import EmailService
            from business.models import Bussiness
            from finance.invoicing.pdf_generator import generate_quotation_pdf
            
            # Get company info
            company = None
            if quotation.branch:
                company = quotation.branch.business if hasattr(quotation.branch, 'business') else Bussiness.objects.first()
            else:
                company = Bussiness.objects.first()
            
            context = {
                'customer_name': quotation.customer.business_name or f"{quotation.customer.user.first_name} {quotation.customer.user.last_name}".strip(),
                'quotation_number': quotation.quotation_number,
                'quotation_date': quotation.quotation_date.strftime('%d/%m/%Y'),
                'valid_until': quotation.valid_until.strftime('%d/%m/%Y'),
                'total_amount': f"{quotation.total:,.2f}",
                'introduction': custom_message or quotation.introduction,
                'customer_notes': quotation.customer_notes,
                'quotation_url': f"{request.build_absolute_uri('/')[:-1]}/finance/quotations/{quotation.id}",
                'company_name': company.name if company else 'Company',
                'year': timezone.now().year
            }
            
            # Generate PDF attachment
            company_info = {
                'name': company.name if company else 'Company',
                'address': company.address if company else '',
                'email': company.email if company else '',
                'phone': company.contact_number if company else '',
            } if company else None
            
            pdf_bytes = generate_quotation_pdf(quotation, company_info)
            
            # Send email with PDF attachment
            email_service = EmailService()
            email_service.send_django_template_email(
                template_name='notifications/email/quotation_sent.html',
                context=context,
                subject=f'Quotation {quotation.quotation_number} from {company.name if company else "Company"}',
                recipient_list=[email_to],
                cc=send_copy_to if send_copy_to else None,
                attachments=[
                    (f'Quotation_{quotation.quotation_number}.pdf', pdf_bytes, 'application/pdf')
                ],
                async_send=True
            )
            
            # Mark as sent
            quotation.mark_as_sent(user=request.user)
            
            # Log email
            QuotationEmailLog.objects.create(
                quotation=quotation,
                email_type='sent',
                recipient_email=email_to,
                status='sent'
            )
            
            return APIResponse.success(
                data=QuotationSerializer(quotation).data,
                message=f'Quotation {quotation.quotation_number} sent successfully to {email_to}'
            )
            
        except Exception as e:
            return APIResponse.error(message=f'Failed to send quotation: {str(e)}')
    
    @action(detail=True, methods=['post'], url_path='mark-as-sent')
    def mark_sent(self, request, pk=None):
        """Mark quotation as sent without actually sending email"""
        quotation = self.get_object()
        quotation.mark_as_sent(user=request.user)
        
        return APIResponse.success(
            data=QuotationSerializer(quotation).data,
            message='Quotation marked as sent'
        )
    
    @action(detail=True, methods=['post'], url_path='accept')
    def accept_quotation(self, request, pk=None):
        """Mark quotation as accepted by customer"""
        quotation = self.get_object()
        
        if quotation.status == 'expired':
            return APIResponse.bad_request(
                message='Cannot accept an expired quotation'
            )
        
        quotation.mark_as_accepted(user=request.user)
        
        return APIResponse.success(
            data=QuotationSerializer(quotation).data,
            message='Quotation accepted successfully'
        )
    
    @action(detail=True, methods=['post'], url_path='decline')
    def decline_quotation(self, request, pk=None):
        """Mark quotation as declined"""
        quotation = self.get_object()
        reason = request.data.get('reason', '')
        
        quotation.mark_as_declined(reason=reason)
        
        return APIResponse.success(
            data=QuotationSerializer(quotation).data,
            message='Quotation declined'
        )
    
    @action(detail=True, methods=['post'], url_path='convert-to-invoice')
    def convert_to_invoice(self, request, pk=None):
        """
        Convert quotation to invoice - KEY FEATURE for sales workflow
        """
        quotation = self.get_object()
        serializer = QuotationConvertSerializer(data=request.data)
        
        if not serializer.is_valid():
            return APIResponse.bad_request(
                message='Invalid data',
                errors=serializer.errors
            )
        
        if quotation.is_converted:
            return APIResponse.bad_request(
                message='This quotation has already been converted to an invoice'
            )
        
        if quotation.status == 'expired':
            return APIResponse.bad_request(
                message='Cannot convert an expired quotation. Please create a new one.'
            )
        
        try:
            invoice = quotation.convert_to_invoice(user=request.user)
            
            # Update payment terms if specified
            payment_terms = serializer.validated_data.get('payment_terms')
            if payment_terms:
                invoice.payment_terms = payment_terms
                invoice.save(update_fields=['payment_terms'])
            
            from finance.invoicing.serializers import InvoiceSerializer
            
            return APIResponse.success(
                data={
                    'invoice': InvoiceSerializer(invoice).data,
                    'quotation': QuotationSerializer(quotation).data
                },
                message=f'Quotation {quotation.quotation_number} converted to invoice {invoice.invoice_number} successfully'
            )
        
        except ValueError as e:
            return APIResponse.bad_request(message=str(e))
        except Exception as e:
            return APIResponse.error(message=str(e))
    
    @action(detail=True, methods=['post'], url_path='clone')
    def clone_quotation(self, request, pk=None):
        """Clone a quotation"""
        quotation = self.get_object()
        
        try:
            cloned_quotation = quotation.clone_quotation()
            return APIResponse.success(
                data=QuotationSerializer(cloned_quotation).data,
                message=f'Quotation cloned successfully as {cloned_quotation.quotation_number}'
            )
        except Exception as e:
            return APIResponse.error(message=str(e))
    
    @action(detail=True, methods=['post'], url_path='generate-share-link')
    def generate_share_link(self, request, pk=None):
        """
        Generate a public shareable link for the quotation
        """
        quotation = self.get_object()
        
        try:
            # Generate share token if not exists
            token = quotation.generate_share_token()
            public_url = quotation.get_public_share_url(request)
            
            # Update allow_public_payment flag
            allow_payment = request.data.get('allow_payment', False)
            if allow_payment:
                quotation.allow_public_payment = True
                quotation.save(update_fields=['allow_public_payment'])
            
            return APIResponse.success(
                data={
                    'id': quotation.id,
                    'url': public_url,
                    'token': token,
                    'is_shared': quotation.is_shared,
                    'allow_payment': quotation.allow_public_payment
                },
                message='Share link generated successfully'
            )
        except Exception as e:
            return APIResponse.error(
                error_code='SHARE_LINK_ERROR',
                message=f'Failed to generate share link: {str(e)}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], url_path='send-follow-up')
    def send_follow_up(self, request, pk=None):
        """Send follow-up reminder"""
        quotation = self.get_object()
        
        if quotation.status in ['accepted', 'declined', 'cancelled', 'converted']:
            return APIResponse.bad_request(
                message='Cannot send follow-up for this quotation status'
            )
        
        quotation.send_follow_up_reminder()
        
        # Log email
        QuotationEmailLog.objects.create(
            quotation=quotation,
            email_type='reminder',
            recipient_email=quotation.customer.user.email,
            status='sent'
        )
        
        return APIResponse.success(
            data=QuotationSerializer(quotation).data,
            message='Follow-up reminder sent successfully'
        )
    
    @action(detail=False, methods=['get'], url_path='summary')
    def quotation_summary(self, request):
        """Get quotation summary statistics"""
        queryset = self.get_queryset()
        
        total_quotations = queryset.count()
        draft_count = queryset.filter(status='draft').count()
        sent_count = queryset.filter(status='sent').count()
        accepted_count = queryset.filter(status='accepted').count()
        declined_count = queryset.filter(status='declined').count()
        converted_count = queryset.filter(is_converted=True).count()
        expired_count = queryset.filter(status='expired').count()
        
        total_value = queryset.aggregate(Sum('total'))['total__sum'] or 0
        accepted_value = queryset.filter(status='accepted').aggregate(Sum('total'))['total__sum'] or 0
        converted_value = queryset.filter(is_converted=True).aggregate(Sum('total'))['total__sum'] or 0
        
        # Conversion rate
        sent_or_viewed = queryset.filter(status__in=['sent', 'viewed', 'accepted', 'converted']).count()
        conversion_rate = (converted_count / sent_or_viewed * 100) if sent_or_viewed > 0 else 0
        
        data = {
            'total_quotations': total_quotations,
            'draft': draft_count,
            'sent': sent_count,
            'accepted': accepted_count,
            'declined': declined_count,
            'converted': converted_count,
            'expired': expired_count,
            'total_value': float(total_value),
            'accepted_value': float(accepted_value),
            'converted_value': float(converted_value),
            'conversion_rate': round(conversion_rate, 2),
        }
        
        return APIResponse.success(data=data)
    
    @action(detail=False, methods=['get'], url_path='pending')
    def pending_quotations(self, request):
        """Get quotations pending customer action"""
        queryset = self.get_queryset().filter(
            status__in=['sent', 'viewed'],
            is_converted=False,
            valid_until__gte=timezone.now().date()
        )
        
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)
    
    @action(detail=True, methods=['get'], url_path='download-pdf')
    def download_pdf(self, request, pk=None):
        """
        Download quotation as PDF
        Professional print-ready quotation document
        """
        try:
            quotation = self.get_object()
            
            # Get company info from branch/business
            company_info = None
            if quotation.branch:
                company_info = {
                    'name': quotation.branch.business.name if hasattr(quotation.branch, 'business') else 'Company Name',
                    'address': getattr(quotation.branch, 'address', ''),
                    'email': getattr(quotation.branch, 'email', ''),
                    'phone': getattr(quotation.branch, 'phone', ''),
                }
            
            # Generate PDF
            pdf_bytes = generate_quotation_pdf(quotation, company_info)
            
            # Return as downloadable file
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="Quotation_{quotation.quotation_number}.pdf"'
            return response
            
        except Exception as e:
            return APIResponse.error(message=str(e))
    
    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf_stream(self, request, pk=None):
        """
        Stream quotation as PDF for inline preview or download
        Query Parameters:
        - download: 'true' to force download, 'false' (default) for inline preview
        """
        try:
            quotation = self.get_object()
            
            # Get company info from branch/business
            company_info = None
            if quotation.branch:
                company_info = {
                    'name': quotation.branch.business.name if hasattr(quotation.branch, 'business') else 'Company Name',
                    'address': getattr(quotation.branch, 'address', ''),
                    'email': getattr(quotation.branch, 'email', ''),
                    'phone': getattr(quotation.branch, 'phone', ''),
                }
            
            # Generate PDF
            pdf_bytes = generate_quotation_pdf(quotation, company_info)
            
            # Determine if download or inline
            download = request.query_params.get('download', 'false').lower() == 'true'
            disposition = 'attachment' if download else 'inline'
            
            # Return PDF as HTTP response
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'{disposition}; filename="Quotation_{quotation.quotation_number}.pdf"'
            response['Cache-Control'] = 'public, max-age=3600'  # Cache for 1 hour
            
            return response
            
        except Quotation.DoesNotExist:
            return HttpResponse('Quotation not found', status=404, content_type='text/plain')
        except Exception as e:
            return HttpResponse(f'Error generating PDF: {str(e)}', status=500, content_type='text/plain')
    
    @action(detail=False, methods=['post'], url_path='bulk-send')
    def bulk_send(self, request):
        """
        Bulk send multiple quotations at once
        """
        quotation_ids = request.data.get('quotation_ids', [])
        
        if not quotation_ids:
            return APIResponse.bad_request(message='No quotations selected')
        
        try:
            quotations = Quotation.objects.filter(id__in=quotation_ids, status='draft')
            
            if not quotations.exists():
                return APIResponse.bad_request(message='No valid draft quotations found')
            
            from notifications.services.email_service import EmailService
            from business.models import Bussiness
            from finance.invoicing.pdf_generator import generate_quotation_pdf
            
            company = Bussiness.objects.first()
            email_service = EmailService()
            
            sent_count = 0
            failed_count = 0
            results = []
            
            for quotation in quotations:
                try:
                    email_to = quotation.customer.user.email
                    
                    context = {
                        'customer_name': quotation.customer.business_name or f"{quotation.customer.user.first_name} {quotation.customer.user.last_name}".strip(),
                        'quotation_number': quotation.quotation_number,
                        'quotation_date': quotation.quotation_date.strftime('%d/%m/%Y'),
                        'valid_until': quotation.valid_until.strftime('%d/%m/%Y'),
                        'total_amount': f"{quotation.total:,.2f}",
                        'introduction': quotation.introduction,
                        'customer_notes': quotation.customer_notes,
                        'quotation_url': f"{request.build_absolute_uri('/')[:-1]}/finance/quotations/{quotation.id}",
                        'company_name': company.name if company else 'Company',
                        'year': timezone.now().year
                    }
                    
                    # Generate PDF
                    company_info = {
                        'name': company.name if company else 'Company',
                        'address': company.address if company else '',
                        'email': company.email if company else '',
                        'phone': company.contact_number if company else '',
                    } if company else None
                    
                    pdf_bytes = generate_quotation_pdf(quotation, company_info)
                    
                    # Send email
                    email_service.send_django_template_email(
                        template_name='notifications/email/quotation_sent.html',
                        context=context,
                        subject=f'Quotation {quotation.quotation_number} from {company.name if company else "Company"}',
                        recipient_list=[email_to],
                        attachments=[
                            (f'Quotation_{quotation.quotation_number}.pdf', pdf_bytes, 'application/pdf')
                        ],
                        async_send=True
                    )
                    
                    # Mark as sent
                    quotation.mark_as_sent(user=request.user)
                    
                    # Log email
                    QuotationEmailLog.objects.create(
                        quotation=quotation,
                        email_type='sent',
                        recipient_email=email_to,
                        status='sent'
                    )
                    
                    sent_count += 1
                    results.append({
                        'quotation_number': quotation.quotation_number,
                        'status': 'sent',
                        'recipient': email_to
                    })
                    
                except Exception as e:
                    failed_count += 1
                    results.append({
                        'quotation_number': quotation.quotation_number,
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




class QuotationEmailLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Quotation Email Log (Read-only)"""
    queryset = QuotationEmailLog.objects.all()
    serializer_class = QuotationEmailLogSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['quotation', 'email_type', 'status']
    ordering = ['-sent_at']


class PublicQuotationView(APIView):
    """
    Public API endpoint for viewing quotations via share token
    Allows unauthenticated access to shared quotations
    """
    permission_classes = [AllowAny]
    
    def get(self, request, quotation_id, token):
        """Retrieve quotation by ID and share token"""
        try:
            quotation = Quotation.objects.get(id=quotation_id, share_token=token, is_shared=True)
            
            # Mark as viewed if customer is viewing
            if hasattr(quotation, 'mark_as_viewed'):
                quotation.mark_as_viewed()
            
            serializer = QuotationSerializer(quotation)
            return APIResponse.success(
                data=serializer.data,
                message='Quotation retrieved successfully'
            )
        except Quotation.DoesNotExist:
            return APIResponse.error(
                error_code='QUOTATION_NOT_FOUND',
                message='Quotation not found or access denied',
                status_code=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return APIResponse.error(
                error_code='QUOTATION_VIEW_ERROR',
                message=f'Error retrieving quotation: {str(e)}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

