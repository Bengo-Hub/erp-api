from datetime import datetime
from django.db import models
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import SupplierPerformance
from .serializers import SupplierPerformanceSerializer
from core_orders.models import BaseOrder
from procurement.purchases.models import Purchase


class SupplierPerformanceViewSet(viewsets.ModelViewSet):
    queryset = SupplierPerformance.objects.all()
    serializer_class = SupplierPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['supplier__user__first_name', 'supplier__user__last_name']
    ordering_fields = ['period_start', 'period_end', 'total_spend']

    @action(detail=False, methods=['get'], url_path='compute')
    def compute(self, request):
        supplier_id = request.query_params.get('supplier')
        start = request.query_params.get('start_date')
        end = request.query_params.get('end_date')
        try:
            start_date = datetime.fromisoformat(start).date() if start else None
            end_date = datetime.fromisoformat(end).date() if end else None
        except ValueError:
            return Response({'detail': 'Invalid date format.'}, status=400)

        if not supplier_id or not start_date or not end_date:
            return Response({'detail': 'supplier, start_date and end_date are required.'}, status=400)

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

        perf, _ = SupplierPerformance.objects.update_or_create(
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
        return Response(self.get_serializer(perf).data)


# Create your views here.
