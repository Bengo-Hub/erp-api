from django.db import models
from decimal import Decimal
from crm.contacts.models import Contact
from crm.leads.models import Lead


class PipelineStage(models.Model):
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)
    is_won = models.BooleanField(default=False)
    is_lost = models.BooleanField(default=False)

    class Meta:
        db_table = 'crm_pipeline_stages'
        ordering = ['order']
        indexes = [
            models.Index(fields=['name'], name='idx_pipeline_stage_name'),
            models.Index(fields=['order'], name='idx_pipeline_stage_order'),
            models.Index(fields=['is_won'], name='idx_pipeline_stage_is_won'),
            models.Index(fields=['is_lost'], name='idx_pipeline_stage_is_lost'),
        ]

    def __str__(self) -> str:
        return self.name


class Deal(models.Model):
    title = models.CharField(max_length=255)
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='deals')
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name='deals')
    stage = models.ForeignKey(PipelineStage, on_delete=models.PROTECT, related_name='deals')
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    close_date = models.DateField(null=True, blank=True)
    owner = models.ForeignKey('authmanagement.CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'crm_deals'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['stage'], name='idx_deal_stage'),
            models.Index(fields=['contact'], name='idx_deal_contact'),
            models.Index(fields=['lead'], name='idx_deal_lead'),
            models.Index(fields=['owner'], name='idx_deal_owner'),
            models.Index(fields=['close_date'], name='idx_deal_close_date'),
            models.Index(fields=['created_at'], name='idx_deal_created_at'),
            models.Index(fields=['updated_at'], name='idx_deal_updated_at'),
        ]

    def __str__(self) -> str:
        return self.title


