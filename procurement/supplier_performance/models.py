from django.db import models
from decimal import Decimal
from django.utils import timezone
from crm.contacts.models import Contact
from core_orders.models import BaseOrder
from procurement.purchases.models import Purchase


class SupplierPerformance(models.Model):
    supplier = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='performance_metrics')
    period_start = models.DateField()
    period_end = models.DateField()
    on_time_delivery_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    defect_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    average_lead_time_days = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal('0.00'))
    total_spend = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'proc_supplier_performance'
        indexes = [
            models.Index(fields=['supplier'], name='idx_sup_perf_supplier'),
            models.Index(fields=['period_start'], name='idx_sup_perf_start'),
            models.Index(fields=['period_end'], name='idx_sup_perf_end'),
            models.Index(fields=['on_time_delivery_rate'], name='idx_sup_perf_delivery_rate'),
            models.Index(fields=['defect_rate'], name='idx_sup_perf_defect_rate'),
            models.Index(fields=['average_lead_time_days'], name='idx_sup_perf_lead_time'),
            models.Index(fields=['total_spend'], name='idx_sup_perf_total_spend'),
            models.Index(fields=['created_at'], name='idx_sup_perf_created'),
            models.Index(fields=['supplier', 'period_start', 'period_end'], name='idx_sup_perf_period'),
        ]

    def __str__(self) -> str:
        return f"{self.supplier} {self.period_start} - {self.period_end}"


# Create your models here.
