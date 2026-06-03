from django.contrib import admin

from .models import EventOutbox, ExchangeRateAPISettings

# Payment/KRA/bank/government/webhook integration config moved to treasury-api.
# Only the generic event outbox + FX (exchange-rate) settings remain in the ERP.


@admin.register(EventOutbox)
class EventOutboxAdmin(admin.ModelAdmin):
    list_display = ['subject', 'aggregate_type', 'status', 'attempts', 'created_at', 'published_at']
    list_filter = ['status', 'aggregate_type']
    search_fields = ['subject', 'aggregate_id', 'tenant_id']
    readonly_fields = ['id', 'created_at', 'published_at']


@admin.register(ExchangeRateAPISettings)
class ExchangeRateAPISettingsAdmin(admin.ModelAdmin):
    list_display = ['provider_name', 'source_currency', 'is_active', 'last_fetch_at', 'last_fetch_status']
    list_filter = ['provider', 'is_active', 'last_fetch_status']
