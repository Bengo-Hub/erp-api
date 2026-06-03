import uuid as _uuid
from django.db import models
from .utils import Crypto
from datetime import time as _time


class EventOutbox(models.Model):
    """Transactional outbox for publishing domain events to NATS JetStream.

    Rows are inserted in the same DB transaction as the domain change (see
    ``integrations.events.publish_event``); a background drain worker
    (``manage.py drain_outbox``) publishes pending rows and marks them sent.
    Subject follows the platform convention ``{aggregate_type}.{event_type}``
    e.g. ``erp.purchase_order.received`` (shared-docs/event-architecture.md).
    """

    STATUS_PENDING = "pending"
    STATUS_PUBLISHED = "published"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    subject = models.CharField(max_length=255, help_text="NATS subject, e.g. erp.purchase_order.received")
    aggregate_type = models.CharField(max_length=64, default="erp")
    aggregate_id = models.CharField(max_length=128, blank=True, default="")
    tenant_id = models.CharField(max_length=64, blank=True, default="")
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Event Outbox"
        verbose_name_plural = "Event Outbox"
        indexes = [
            models.Index(fields=["status", "created_at"], name="idx_outbox_status_created"),
            models.Index(fields=["subject"], name="idx_outbox_subject"),
        ]

    def __str__(self):
        return f"{self.subject} [{self.status}]"


class ExchangeRateAPISettings(models.Model):
    """
    Configuration for external exchange rate API integration.
    Used to fetch live exchange rates from providers like exchangerate.host.

    This is the only payment/finance-adjacent config the ERP retains: the daily
    FX fetch (integrations.tasks) updates core.ExchangeRate so HR/ops figures can
    be normalised. All payment gateways + fiscalisation config moved to treasury-api.
    """
    PROVIDER_CHOICES = [
        ('EXCHANGERATE_HOST', 'exchangerate.host'),
        ('OPEN_EXCHANGE', 'Open Exchange Rates'),
        ('FIXER', 'Fixer.io'),
        ('CURRENCY_LAYER', 'Currency Layer'),
        ('OTHER', 'Other Provider'),
    ]

    # Provider identification
    provider = models.CharField(
        max_length=50,
        choices=PROVIDER_CHOICES,
        default='EXCHANGERATE_HOST',
        help_text="Exchange rate API provider"
    )
    provider_name = models.CharField(
        max_length=255,
        default='exchangerate.host',
        help_text="Display name for the provider"
    )

    # API Configuration
    api_endpoint = models.URLField(
        default='https://api.exchangerate.host/live',
        help_text="API endpoint URL for fetching rates"
    )
    access_key = models.CharField(
        max_length=1500,
        blank=True,
        null=True,
        help_text="API access key (will be encrypted)"
    )

    # Currency configuration
    source_currency = models.CharField(
        max_length=3,
        default='USD',
        help_text="Base/source currency for rate queries"
    )
    target_currencies = models.JSONField(
        default=list,
        help_text="List of target currencies to fetch rates for (e.g., ['KES', 'EUR', 'GBP'])"
    )

    # Scheduling configuration
    fetch_time = models.TimeField(
        default=_time(0, 0),
        help_text="Time of day to fetch exchange rates (24hr format)"
    )
    last_fetch_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of last successful rate fetch"
    )
    last_fetch_status = models.CharField(
        max_length=20,
        choices=[
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('pending', 'Pending'),
        ],
        default='pending',
        help_text="Status of the last fetch operation"
    )
    last_fetch_error = models.TextField(
        blank=True,
        null=True,
        help_text="Error message from last failed fetch"
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        help_text="Enable/disable automatic rate fetching"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Auto-encrypt sensitive fields before saving"""
        # Encrypt access key if not already encrypted
        if self.access_key and "gAAAAA" not in str(self.access_key):
            self.access_key = Crypto(self.access_key, 'encrypt').encrypt()

        # Ensure target_currencies is a list
        if not self.target_currencies:
            self.target_currencies = ['KES', 'USD', 'EUR', 'GBP']

        super().save(*args, **kwargs)

    def get_decrypted_access_key(self):
        """Return decrypted access key for API calls"""
        if self.access_key and "gAAAAA" in str(self.access_key):
            return Crypto(self.access_key, 'decrypt').decrypt()
        return self.access_key

    def __str__(self):
        status = 'Active' if self.is_active else 'Inactive'
        return f"Exchange Rate API - {self.provider_name} ({status})"

    class Meta:
        verbose_name = "Exchange Rate API Settings"
        verbose_name_plural = "Exchange Rate API Settings"
        indexes = [
            models.Index(fields=['provider'], name='idx_exchange_rate_provider'),
            models.Index(fields=['is_active'], name='idx_exchange_rate_active'),
        ]
