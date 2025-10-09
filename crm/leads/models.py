from django.db import models
from decimal import Decimal
from django.utils import timezone
from crm.contacts.models import Contact


class Lead(models.Model):
    STATUS_CHOICES = (
        ("new", "New"),
        ("contacted", "Contacted"),
        ("qualified", "Qualified"),
        ("won", "Won"),
        ("lost", "Lost"),
    )
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='leads')
    source = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    owner = models.ForeignKey('authmanagement.CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'crm_leads'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status'], name='idx_lead_status'),
            models.Index(fields=['contact'], name='idx_lead_contact'),
            models.Index(fields=['source'], name='idx_lead_source'),
            models.Index(fields=['owner'], name='idx_lead_owner'),
            models.Index(fields=['created_at'], name='idx_lead_created_at'),
            models.Index(fields=['updated_at'], name='idx_lead_updated_at'),
        ]

    def __str__(self) -> str:
        return f"{self.contact} - {self.status}"


