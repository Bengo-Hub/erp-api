from datetime import datetime
from django.db import models
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import SupplierPerformance
from .serializers import SupplierPerformanceSerializer
from core_orders.models import BaseOrder
from procurement.purchases.models import Purchase
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class SupplierPerformanceViewSet(BaseModelViewSet):
    queryset = SupplierPerformance.objects.all().select_related('supplier')
    serializer_class = SupplierPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['supplier__user__first_name', 'supplier__user__last_name']
    ordering_fields = ['period_start', 'period_end', 'total_spend']

    @action(detail=False, methods=['get'], url_path='compute')
    def compute(self, request):
        """Compute supplier performance metrics for date range."""
        try:
            correlation_id = get_correlation_id(request)
            supplier_id = request.query_params.get('supplier')
            start = request.query_params.get('start_date')
            end = request.query_params.get('end_date')
            
            if not supplier_id or not start or not end:
                return APIResponse.bad_request(
                    message='supplier, start_date and end_date are required',
                    error_id='missing_parameters',
                    correlation_id=correlation_id
                )
            
            try:
                start_date = datetime.fromisoformat(start).date()
                end_date = datetime.fromisoformat(end).date()
            except ValueError:
                return APIResponse.validation_error(
                    message='Invalid date format. Use ISO format (YYYY-MM-DD)',
                    errors={'dates': 'Invalid date format'},
                    correlation_id=correlation_id
                )

            po_qs = BaseOrder.objects.filter(supplier_id=supplier_id, created_at__date__gte=start_date, created_at__date__lte=end_date)
            purchases_qs = Purchase.objects.filter(supplier_id=supplier_id, date_added__date__gte=start_date, date_added__date__lte=end_date)

            total_pos = po_qs.count()
            on_time = 0
            for po in po_qs:
                purchase = Purchase.objects.filter(purchase_order=po).first()
                if po.expected_delivery and purchase and purchase.date_added:
                    on_time += 1 if purchase.date_added.date() <= po.expected_delivery else 0

            on_time_rate = round((on_time / total_pos) * 100, 2) if total_pos else 0
            total_spend = purchases_qs.aggregate(amount=models.Sum('grand_total'))['amount'] or 0

            # Placeholder for defect rate and lead time until quality and GRN data exist
            defect_rate = 0
            avg_lead_days = 0

            perf, created = SupplierPerformance.objects.update_or_create(
                supplier_id=supplier_id,
                period_start=start_date,
                period_end=end_date,
                defaults={
                    'on_time_delivery_rate': on_time_rate,
                    'defect_rate': defect_rate,
                    'average_lead_time_days': avg_lead_days,
                    'total_spend': total_spend,
                }
            )
            
            # Log performance computation
            AuditTrail.log(
                operation=AuditTrail.EXPORT,
                module='procurement',
                entity_type='SupplierPerformance',
                entity_id=perf.id,
                user=request.user,
                reason=f'Computed supplier performance for supplier {supplier_id}',
                request=request
            )
            
            return APIResponse.success(
                data=self.get_serializer(perf).data,
                message='Supplier performance computed successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error computing supplier performance: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error computing supplier performance',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )


# Create your views here.
