from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from datetime import datetime, timedelta
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone as tz

from .models import TaxCategory, Tax, TaxGroup, TaxGroupItem, TaxPeriod
from .serializers import TaxCategorySerializer, TaxSerializer, TaxGroupSerializer, TaxGroupItemSerializer, TaxPeriodSerializer
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class TaxCategoryViewSet(BaseModelViewSet):
    queryset = TaxCategory.objects.all()
    serializer_class = TaxCategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'description']
    filterset_fields = ['business', 'is_active']


class TaxViewSet(BaseModelViewSet):
    queryset = Tax.objects.all().select_related('business', 'category')
    serializer_class = TaxSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'description', 'tax_number']
    filterset_fields = ['business', 'category', 'is_active', 'is_default', 'calculation_type']
    
    @action(detail=False, methods=['get'])
    def default_for_business(self, request):
        """Get the default tax for a specific business"""
        try:
            correlation_id = get_correlation_id(request)
            business_id = request.query_params.get('business_id')
            
            if not business_id:
                return APIResponse.bad_request(
                    message='Business ID is required',
                    error_id='missing_business_id',
                    correlation_id=correlation_id
                )
                
            tax = Tax.objects.filter(business_id=business_id, is_default=True).first()
            if not tax:
                return APIResponse.not_found(
                    message='No default tax found for this business',
                    correlation_id=correlation_id
                )
                
            serializer = self.get_serializer(tax)
            return APIResponse.success(
                data=serializer.data,
                message='Default tax retrieved successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error fetching default tax: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error retrieving default tax',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )
    
    def perform_create(self, serializer):
        tax = serializer.save()
        # If this is marked as default, ensure no other taxes for this business are default
        if tax.is_default:
            Tax.objects.filter(business=tax.business, is_default=True).exclude(pk=tax.pk).update(is_default=False)


class TaxGroupViewSet(BaseModelViewSet):
    queryset = TaxGroup.objects.all().select_related('business')
    serializer_class = TaxGroupSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'description']
    filterset_fields = ['business', 'is_active']
    
    @action(detail=True, methods=['post'])
    def add_tax(self, request, pk=None):
        """Add a tax to this tax group"""
        try:
            correlation_id = get_correlation_id(request)
            tax_group = self.get_object()
            tax_id = request.data.get('tax_id')
            order = request.data.get('order', 0)
            
            if not tax_id:
                return APIResponse.bad_request(
                    message='Tax ID is required',
                    error_id='missing_tax_id',
                    correlation_id=correlation_id
                )
                
            tax = get_object_or_404(Tax, pk=tax_id)
            
            # Ensure the tax belongs to the same business as the group
            if getattr(tax, 'business_id', None) != getattr(tax_group, 'business_id', None):
                return APIResponse.bad_request(
                    message='Tax and tax group must belong to the same business',
                    error_id='business_mismatch',
                    correlation_id=correlation_id
                )
                
            # Check if the tax is already in the group
            if TaxGroupItem.objects.filter(tax_group=tax_group, tax=tax).exists():
                return APIResponse.bad_request(
                    message='Tax is already in this group',
                    error_id='tax_already_in_group',
                    correlation_id=correlation_id
                )
            
            # Add the tax to the group
            tax_group_item = TaxGroupItem.objects.create(
                tax_group=tax_group,
                tax=tax,
                order=order
            )
            
            serializer = TaxGroupItemSerializer(tax_group_item)
            return APIResponse.created(
                data=serializer.data,
                message='Tax added to group successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error adding tax to group: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error adding tax to group',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )
    
    @action(detail=True, methods=['delete'])
    def remove_tax(self, request, pk=None):
        """Remove a tax from this tax group"""
        try:
            correlation_id = get_correlation_id(request)
            tax_group = self.get_object()
            tax_id = request.query_params.get('tax_id')
            
            if not tax_id:
                return APIResponse.bad_request(
                    message='Tax ID is required',
                    error_id='missing_tax_id',
                    correlation_id=correlation_id
                )
                
            tax_group_item = TaxGroupItem.objects.get(tax_group=tax_group, tax_id=tax_id)
            tax_group_item.delete()
            return APIResponse.no_content(
                message='Tax removed from group successfully',
                correlation_id=correlation_id
            )
        except TaxGroupItem.DoesNotExist:
            return APIResponse.not_found(
                message='Tax is not in this group',
                correlation_id=get_correlation_id(request)
            )
        except Exception as e:
            logger.error(f'Error removing tax from group: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error removing tax from group',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )


class TaxPeriodViewSet(BaseModelViewSet):
    queryset = TaxPeriod.objects.all().order_by('-start_date')
    serializer_class = TaxPeriodSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'notes']
    filterset_fields = ['business', 'period_type', 'status']
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update the status of a tax period"""
        try:
            correlation_id = get_correlation_id(request)
            tax_period = self.get_object()
            status_value = request.data.get('status')
            notes = request.data.get('notes', '')
            
            if not status_value or status_value not in [s[0] for s in TaxPeriod.STATUS_CHOICES]:
                return APIResponse.bad_request(
                    message='Valid status is required',
                    error_id='invalid_status',
                    correlation_id=correlation_id
                )
                
            # Update the tax period
            old_status = tax_period.status
            tax_period.status = status_value
            
            if notes:
                if tax_period.notes:
                    tax_period.notes += f"\n\n{datetime.now().strftime('%Y-%m-%d %H:%M')} - Status changed from {old_status} to {status_value}:\n{notes}"
                else:
                    tax_period.notes = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} - Status changed from {old_status} to {status_value}:\n{notes}"
            
            tax_period.save()
            
            serializer = self.get_serializer(tax_period)
            return APIResponse.success(
                data=serializer.data,
                message='Tax period status updated successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error updating tax period status: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error updating tax period status',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )
    
    @action(detail=True, methods=['post'])
    def calculate_totals(self, request, pk=None):
        """Calculate total taxes collected and paid for this period"""
        try:
            correlation_id = get_correlation_id(request)
            tax_period = self.get_object()
            
            # Here you would normally implement logic to calculate taxes
            # from invoices, expenses, and other financial records
            # For demonstration, we'll just update with the provided values
            
            collected = request.data.get('total_collected')
            paid = request.data.get('total_paid')
            
            if collected is not None:
                tax_period.total_collected = collected
                
            if paid is not None:
                tax_period.total_paid = paid
                
            tax_period.save()
            
            serializer = self.get_serializer(tax_period)
            return APIResponse.success(
                data=serializer.data,
                message='Tax period totals calculated successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error calculating tax period totals: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error calculating tax period totals',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'])
    def file_vat(self, request, pk=None):
        """Mark VAT filed for this period with a KRA reference and timestamp."""
        try:
            correlation_id = get_correlation_id(request)
            tax_period = self.get_object()
            kra_ref = request.data.get('kra_filing_reference')
            if not kra_ref:
                return APIResponse.bad_request(
                    message='kra_filing_reference is required',
                    error_id='missing_kra_filing_reference',
                    correlation_id=correlation_id
                )
            tax_period.kra_filing_reference = kra_ref
            tax_period.filed_at = tz.now()
            tax_period.status = 'filed'
            tax_period.save()
            return APIResponse.success(
                data=self.get_serializer(tax_period).data,
                message='VAT filed successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error filing VAT: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error filing VAT',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """Mark period as paid and set totals if provided."""
        try:
            correlation_id = get_correlation_id(request)
            tax_period = self.get_object()
            collected = request.data.get('total_collected')
            paid = request.data.get('total_paid')
            if collected is not None:
                tax_period.total_collected = collected
            if paid is not None:
                tax_period.total_paid = paid
            tax_period.status = 'paid'
            tax_period.save()
            return APIResponse.success(
                data=self.get_serializer(tax_period).data,
                message='Tax period marked as paid successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error marking tax period as paid: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error marking tax period as paid',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'])
    def file_paye(self, request, pk=None):
        """Mark PAYE filed for this period. Mirrors VAT filing flow."""
        try:
            correlation_id = get_correlation_id(request)
            tax_period = self.get_object()
            kra_ref = request.data.get('kra_filing_reference')
            if not kra_ref:
                return APIResponse.bad_request(
                    message='kra_filing_reference is required',
                    error_id='missing_kra_filing_reference',
                    correlation_id=correlation_id
                )
            tax_period.kra_filing_reference = kra_ref
            tax_period.filed_at = tz.now()
            tax_period.status = 'filed'
            tax_period.save()
            return APIResponse.success(
                data=self.get_serializer(tax_period).data,
                message='PAYE filed successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error filing PAYE: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error filing PAYE',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'], url_path='submit-etims-invoice')
    def submit_etims_invoice(self, request, pk=None):
        """
        Submit a summarized invoice for this tax period to KRA eTIMS.
        Expects payload already aggregated at frontend/backend mapping layer.
        """
        try:
            correlation_id = get_correlation_id(request)
            payload = request.data.get('invoice_payload') or {}
            if not isinstance(payload, dict) or not payload:
                return APIResponse.bad_request(
                    message='invoice_payload is required',
                    error_id='missing_invoice_payload',
                    correlation_id=correlation_id
                )

            # Lazy import to avoid circulars and linter type issues
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.submit_invoice(payload)
            if ok:
                return APIResponse.success(
                    data={'success': True, 'result': result},
                    message='Invoice submitted to KRA eTIMS successfully',
                    correlation_id=correlation_id
                )
            return APIResponse.bad_request(
                message='Failed to submit invoice to KRA eTIMS',
                error_id='kra_etims_submission_failed',
                correlation_id=correlation_id
            )
        except Exception as exc:
            logger.error(f'Error submitting ETIMS invoice: {str(exc)}', exc_info=True)
            return APIResponse.server_error(
                message='Error submitting ETIMS invoice',
                error_id=str(exc),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=False, methods=['get'], url_path='kra/certificate')
    def kra_certificate(self, request):
        try:
            correlation_id = get_correlation_id(request)
            tax_type = request.query_params.get('type')
            period = request.query_params.get('period')
            if not tax_type or not period:
                return APIResponse.bad_request(
                    message='type and period are required',
                    error_id='missing_tax_type_or_period',
                    correlation_id=correlation_id
                )
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.get_tax_certificate(tax_type, period)
            if ok:
                return APIResponse.success(
                    data={'success': True, 'result': result},
                    message='Tax certificate retrieved successfully',
                    correlation_id=correlation_id
                )
            return APIResponse.bad_request(
                message='Failed to retrieve tax certificate from KRA',
                error_id='kra_certificate_retrieval_failed',
                correlation_id=correlation_id
            )
        except Exception as exc:
            logger.error(f'Error retrieving KRA certificate: {str(exc)}', exc_info=True)
            return APIResponse.server_error(
                message='Error retrieving KRA certificate',
                error_id=str(exc),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=False, methods=['get'], url_path='kra/compliance')
    def kra_compliance(self, request):
        try:
            correlation_id = get_correlation_id(request)
            pin = request.query_params.get('pin')
            if not pin:
                return APIResponse.bad_request(
                    message='pin is required',
                    error_id='missing_pin',
                    correlation_id=correlation_id
                )
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.check_compliance(pin)
            if ok:
                return APIResponse.success(
                    data={'success': True, 'result': result},
                    message='Compliance check successful',
                    correlation_id=correlation_id
                )
            return APIResponse.bad_request(
                message='Compliance check failed',
                error_id='kra_compliance_check_failed',
                correlation_id=correlation_id
            )
        except Exception as exc:
            logger.error(f'Error checking KRA compliance: {str(exc)}', exc_info=True)
            return APIResponse.server_error(
                message='Error checking KRA compliance',
                error_id=str(exc),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=False, methods=['post'], url_path='kra/sync')
    def kra_sync(self, request):
        try:
            correlation_id = get_correlation_id(request)
            start_date = request.data.get('start_date')
            end_date = request.data.get('end_date')
            if not start_date or not end_date:
                return APIResponse.bad_request(
                    message='start_date and end_date are required',
                    error_id='missing_start_or_end_date',
                    correlation_id=correlation_id
                )
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.sync_tax_data(start_date, end_date)
            if ok:
                return APIResponse.success(
                    data={'success': True, 'result': result},
                    message='Tax data synced successfully',
                    correlation_id=correlation_id
                )
            return APIResponse.bad_request(
                message='Failed to sync tax data with KRA',
                error_id='kra_tax_data_sync_failed',
                correlation_id=correlation_id
            )
        except Exception as exc:
            logger.error(f'Error syncing KRA tax data: {str(exc)}', exc_info=True)
            return APIResponse.server_error(
                message='Error syncing KRA tax data',
                error_id=str(exc),
                correlation_id=get_correlation_id(request)
            )