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


class TaxCategoryViewSet(viewsets.ModelViewSet):
    queryset = TaxCategory.objects.all()
    serializer_class = TaxCategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'description']
    filterset_fields = ['business', 'is_active']
    

class TaxViewSet(viewsets.ModelViewSet):
    queryset = Tax.objects.all()
    serializer_class = TaxSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'description', 'tax_number']
    filterset_fields = ['business', 'category', 'is_active', 'is_default', 'calculation_type']
    
    @action(detail=False, methods=['get'])
    def default_for_business(self, request):
        """Get the default tax for a specific business"""
        business_id = request.query_params.get('business_id')
        if not business_id:
            return Response({"error": "Business ID is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        tax = Tax.objects.filter(business_id=business_id, is_default=True).first()
        if not tax:
            return Response({"error": "No default tax found for this business"}, status=status.HTTP_404_NOT_FOUND)
            
        serializer = self.get_serializer(tax)
        return Response(serializer.data)
    
    def perform_create(self, serializer):
        tax = serializer.save()
        # If this is marked as default, ensure no other taxes for this business are default
        if tax.is_default:
            Tax.objects.filter(business=tax.business, is_default=True).exclude(pk=tax.pk).update(is_default=False)


class TaxGroupViewSet(viewsets.ModelViewSet):
    queryset = TaxGroup.objects.all()
    serializer_class = TaxGroupSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'description']
    filterset_fields = ['business', 'is_active']
    
    @action(detail=True, methods=['post'])
    def add_tax(self, request, pk=None):
        """Add a tax to this tax group"""
        tax_group = self.get_object()
        tax_id = request.data.get('tax_id')
        order = request.data.get('order', 0)
        
        if not tax_id:
            return Response({"error": "Tax ID is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        tax = get_object_or_404(Tax, pk=tax_id)
        
        # Ensure the tax belongs to the same business as the group
        if getattr(tax, 'business_id', None) != getattr(tax_group, 'business_id', None):
            return Response({
                "error": "Tax and tax group must belong to the same business"
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # Check if the tax is already in the group
        if TaxGroupItem.objects.filter(tax_group=tax_group, tax=tax).exists():
            return Response({"error": "Tax is already in this group"}, status=status.HTTP_400_BAD_REQUEST)
            
        # Add the tax to the group
        tax_group_item = TaxGroupItem.objects.create(
            tax_group=tax_group,
            tax=tax,
            order=order
        )
        
        serializer = TaxGroupItemSerializer(tax_group_item)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['delete'])
    def remove_tax(self, request, pk=None):
        """Remove a tax from this tax group"""
        tax_group = self.get_object()
        tax_id = request.query_params.get('tax_id')
        
        if not tax_id:
            return Response({"error": "Tax ID is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            tax_group_item = TaxGroupItem.objects.get(tax_group=tax_group, tax_id=tax_id)
            tax_group_item.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TaxGroupItem.DoesNotExist:
            return Response({"error": "Tax is not in this group"}, status=status.HTTP_404_NOT_FOUND)


class TaxPeriodViewSet(viewsets.ModelViewSet):
    queryset = TaxPeriod.objects.all().order_by('-start_date')
    serializer_class = TaxPeriodSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'notes']
    filterset_fields = ['business', 'period_type', 'status']
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update the status of a tax period"""
        tax_period = self.get_object()
        status_value = request.data.get('status')
        notes = request.data.get('notes', '')
        
        if not status_value or status_value not in [s[0] for s in TaxPeriod.STATUS_CHOICES]:
            return Response({"error": "Valid status is required"}, status=status.HTTP_400_BAD_REQUEST)
            
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
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def calculate_totals(self, request, pk=None):
        """Calculate total taxes collected and paid for this period"""
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
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def file_vat(self, request, pk=None):
        """Mark VAT filed for this period with a KRA reference and timestamp."""
        tax_period = self.get_object()
        kra_ref = request.data.get('kra_filing_reference')
        if not kra_ref:
            return Response({"error": "kra_filing_reference is required"}, status=status.HTTP_400_BAD_REQUEST)
        tax_period.kra_filing_reference = kra_ref
        tax_period.filed_at = tz.now()
        tax_period.status = 'filed'
        tax_period.save()
        return Response(self.get_serializer(tax_period).data)

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """Mark period as paid and set totals if provided."""
        tax_period = self.get_object()
        collected = request.data.get('total_collected')
        paid = request.data.get('total_paid')
        if collected is not None:
            tax_period.total_collected = collected
        if paid is not None:
            tax_period.total_paid = paid
        tax_period.status = 'paid'
        tax_period.save()
        return Response(self.get_serializer(tax_period).data)

    @action(detail=True, methods=['post'])
    def file_paye(self, request, pk=None):
        """Mark PAYE filed for this period. Mirrors VAT filing flow."""
        tax_period = self.get_object()
        kra_ref = request.data.get('kra_filing_reference')
        if not kra_ref:
            return Response({"error": "kra_filing_reference is required"}, status=status.HTTP_400_BAD_REQUEST)
        tax_period.kra_filing_reference = kra_ref
        tax_period.filed_at = tz.now()
        tax_period.status = 'filed'
        tax_period.save()
        return Response(self.get_serializer(tax_period).data)

    @action(detail=True, methods=['post'], url_path='submit-etims-invoice')
    def submit_etims_invoice(self, request, pk=None):
        """
        Submit a summarized invoice for this tax period to KRA eTIMS.
        Expects payload already aggregated at frontend/backend mapping layer.
        """
        try:
            payload = request.data.get('invoice_payload') or {}
            if not isinstance(payload, dict) or not payload:
                return Response({'detail': 'invoice_payload is required'}, status=status.HTTP_400_BAD_REQUEST)

            # Lazy import to avoid circulars and linter type issues
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.submit_invoice(payload)
            if ok:
                return Response({'success': True, 'result': result})
            return Response({'success': False, 'error': result}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'success': False, 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='kra/certificate')
    def kra_certificate(self, request):
        tax_type = request.query_params.get('type')
        period = request.query_params.get('period')
        if not tax_type or not period:
            return Response({'detail': 'type and period are required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.get_tax_certificate(tax_type, period)
            if ok:
                return Response({'success': True, 'result': result})
            return Response({'success': False, 'error': result}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'success': False, 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='kra/compliance')
    def kra_compliance(self, request):
        pin = request.query_params.get('pin')
        if not pin:
            return Response({'detail': 'pin is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.check_compliance(pin)
            if ok:
                return Response({'success': True, 'result': result})
            return Response({'success': False, 'error': result}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'success': False, 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='kra/sync')
    def kra_sync(self, request):
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')
        if not start_date or not end_date:
            return Response({'detail': 'start_date and end_date are required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from integrations.services import KRAService  # type: ignore
            kra = KRAService()
            ok, result = kra.sync_tax_data(start_date, end_date)
            if ok:
                return Response({'success': True, 'result': result})
            return Response({'success': False, 'error': result}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'success': False, 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)