from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from crm.contacts.models import Contact
from core.models import BaseModel
from core_orders.models import BaseOrder


class Contract(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("active", "Active"),
        ("expired", "Expired"),
        ("terminated", "Terminated"),
    )
    supplier = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='contracts')
    title = models.CharField(max_length=255)
    start_date = models.DateField()
    end_date = models.DateField()
    value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    terms = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'proc_contracts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['supplier'], name='idx_contract_supplier'),
            models.Index(fields=['title'], name='idx_contract_title'),
            models.Index(fields=['start_date'], name='idx_proc_contract_start'),
            models.Index(fields=['end_date'], name='idx_proc_contract_end'),
            models.Index(fields=['status'], name='idx_proc_contract_status'),
            models.Index(fields=['created_at'], name='idx_contract_created_at'),
            models.Index(fields=['supplier', 'status'], name='idx_contract_supplier_status'),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.status})"


class ContractOrderLink(models.Model):
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='order_links')
    purchase_order = models.ForeignKey(BaseOrder, on_delete=models.CASCADE, related_name='contract_links')

    class Meta:
        db_table = 'proc_contract_order_links'
        unique_together = ('contract', 'purchase_order')
        indexes = [
            models.Index(fields=['contract'], name='idx_proc_colink_contract'),
            models.Index(fields=['purchase_order'], name='idx_proc_colink_po'),
        ]
