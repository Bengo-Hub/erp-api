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

    def _resolve_company_info(self, quotation):
        """Return company info dict using branch (preferred) or business HQ branch."""
        company = None
        name = 'Company'
        email = ''
        phone = ''
        address = ''

        try:
            if getattr(quotation, 'branch', None):
                branch = quotation.branch
                company = getattr(branch, 'business', None)
            else:
                # Fallback to business first available
                company = getattr(quotation, 'branch', None) or None

            # If no branch on quote, try to find the main HQ branch for the business attached to the quotation
            if not getattr(quotation, 'branch', None) and getattr(quotation, 'branch', None) is None:
                # Try to get related business from quotation.customer.business or from Bussiness
                from business.models import Bussiness
                biz = None
                if getattr(quotation, 'branch', None) and getattr(quotation.branch, 'business', None):
                    biz = quotation.branch.business
                else:
                    # Try to locate a business via quotation.branch.business if any
                    try:
                        biz = Bussiness.objects.first()
                    except Exception:
                        biz = None

                branch = None
                if biz:
                    try:
                        branch = biz.branches.filter(is_main_branch=True, is_active=True).first()
                    except Exception:
                        branch = None
                if branch:
                    company = branch.business
            # At this point, prefer branch contact & location
            branch = getattr(quotation, 'branch', None)
            if not branch and company:
                try:
                    branch = company.branches.filter(is_main_branch=True, is_active=True).first()
                except Exception:
                    branch = None

            if company:
                name = getattr(company, 'name', name)

            if branch:
                email = getattr(branch, 'email', '') or getattr(company, 'email', '') if company else ''
                phone = getattr(branch, 'contact_number', '') or getattr(company, 'contact_number', '') if company else ''
                loc = getattr(branch, 'location', None)
                if loc:
                    def _part_val(x):
                        if x is None:
                            return ''
                        if not isinstance(x, str):
                            try:
                                return str(x)
                            except Exception:
                                return getattr(x, 'name', '') or ''
                        return x

                    raw_parts = [getattr(loc, 'building_name', None), getattr(loc, 'street_name', None), getattr(loc, 'city', None), getattr(loc, 'county', None), getattr(loc, 'state', None), getattr(loc, 'country', None)]
                    parts = [_part_val(p).strip() for p in raw_parts if _part_val(p).strip()]
                    address = ', '.join(parts)
            else:
                # fallback: use company-level location
                loc = getattr(company, 'location', None) if company else None
                if loc:
                    def _part_val(x):
                        if x is None:
                            return ''
                        if not isinstance(x, str):
                            try:
                                return str(x)
                            except Exception:
                                return getattr(x, 'name', '') or ''
                        return x

                    raw_parts = [getattr(loc, 'building_name', None), getattr(loc, 'street_name', None), getattr(loc, 'city', None), getattr(loc, 'county', None), getattr(loc, 'state', None), getattr(loc, 'country', None)]
                    parts = [_part_val(p).strip() for p in raw_parts if _part_val(p).strip()]
                    address = ', '.join(parts)

        except Exception:
            pass

        return {
            'name': name,
            'address': address,
            'email': email or '',
            'phone': phone or ''
        }
    
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
            # Resolve company info (prefer branch or HQ branch location)
            company_info = self._resolve_company_info(quotation)
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
            return APIResponse.server_error(message=f'Failed to send quotation: {str(e)}')
    
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
            return APIResponse.server_error(message=str(e))
    
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
            return APIResponse.server_error(message=str(e))
    
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
            
            # Get company info from branch/business (use branch contact/location when available)
            company = quotation.branch.business if getattr(quotation.branch, 'business', None) else None
            company_name = company.name if company else (quotation.branch.business.name if getattr(quotation.branch, 'business', None) else 'Company')
            company_email = getattr(quotation.branch, 'email', None) or getattr(company, 'email', None) or ''
            company_phone = getattr(quotation.branch, 'contact_number', None) or getattr(company, 'contact_number', None) or ''
            from finance.utils import format_location_address
            company_address = format_location_address(quotation.branch.location, fields=['building_name', 'street_name', 'city', 'county']) if quotation.branch else ''

            company_info = {
                'name': company_name,
                'address': company_address,
                'email': company_email,
                'phone': company_phone,
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

            # Ensure DB state is fresh and include related changes (items) before rendering
            try:
                quotation.refresh_from_db()
            except Exception:
                pass

            # Resolve company info (prefer branch/HQ branch)
            company_info = self._resolve_company_info(quotation)
            pdf_bytes = generate_quotation_pdf(quotation, company_info)

            # Determine if download or inline
            download = request.query_params.get('download', 'false').lower() == 'true'
            disposition = 'attachment' if download else 'inline'

            # Build response
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'{disposition}; filename="Quotation_{quotation.quotation_number}.pdf"'

            # Prevent clients from using stale cached PDF - always revalidate
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'

            # Compute last_modified considering related items to ensure changes to items
            # cause a new Last-Modified/ETag value
            from django.db.models import Max
            candidates = []
            q_lm = getattr(quotation, 'updated_at', None) or getattr(quotation, 'created_at', None)
            if q_lm:
                candidates.append(q_lm)

            items_lm = quotation.items.aggregate(max_updated=Max('updated_at'))['max_updated']
            if items_lm:
                candidates.append(items_lm)

            last_modified = max(candidates) if candidates else None
            if last_modified:
                from django.utils.http import http_date
                response['Last-Modified'] = http_date(last_modified.timestamp())

            try:
                import hashlib
                etag_src = f"{quotation.pk}-{getattr(last_modified, 'isoformat', lambda: '')()}-{getattr(quotation, 'total', '')}-{quotation.items.count()}"
                etag = hashlib.sha1(etag_src.encode()).hexdigest()
                response['ETag'] = f'W/"{etag}"'
            except Exception:
                pass

            # Honor conditional requests: If client provides If-None-Match or If-Modified-Since, respond 304 when appropriate
            from django.http import HttpResponseNotModified
            if_none_match = request.META.get('HTTP_IF_NONE_MATCH') or request.headers.get('If-None-Match')
            if if_none_match and response.get('ETag') and if_none_match == response['ETag']:
                return HttpResponseNotModified()

            if_modified_since = request.META.get('HTTP_IF_MODIFIED_SINCE') or request.headers.get('If-Modified-Since')
            if if_modified_since and last_modified:
                # Compare client-provided date to last_modified
                from django.utils.http import parse_http_date_safe
                client_ts = parse_http_date_safe(if_modified_since)
                if client_ts and int(last_modified.timestamp()) <= client_ts:
                    return HttpResponseNotModified()

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

