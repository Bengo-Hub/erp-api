from rest_framework import serializers
from .models import SupplierPerformance


class SupplierPerformanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierPerformance
        fields = [
            'id', 'supplier', 'period_start', 'period_end',
            'on_time_delivery_rate', 'defect_rate', 'average_lead_time_days', 'total_spend',
            'created_at'
        ]


