from django.contrib import admin
from django import forms
from .models import (
    Integrations, MpesaSettings, CardPaymentSettings, PayPalSettings,
    KRASettings, KRACertificateRequest, KRAComplianceCheck,
    WebhookEndpoint, WebhookEvent,
    BankAPISettings, GovernmentServiceSettings
)

# Inline admin classes
class MpesaSettingsInline(admin.StackedInline):
    model = MpesaSettings
    extra = 0
    classes = ['collapse']

# Main admin classes
@admin.register(Integrations)
class IntegrationsAdmin(admin.ModelAdmin):
    list_display = ('name', 'integration_type', 'is_active', 'is_default', 'created_at')
    list_filter = ('integration_type', 'is_active', 'is_default')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('name', 'integration_type', 'is_active', 'is_default')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    def get_inlines(self, request, obj=None):
        if obj is None:
            return []
        
        inlines = []
        if obj.integration_type == 'PAYMENT':
            inlines.append(MpesaSettingsInline)
            
        return inlines


# M-Pesa Settings admin
class MpesaSettingsForm(forms.ModelForm):
    class Meta:
        model = MpesaSettings
        fields = '__all__'
        widgets = {
            'consumer_key': forms.PasswordInput(render_value=True),
            'consumer_secret': forms.PasswordInput(render_value=True),
            'passkey': forms.PasswordInput(render_value=True),
            'security_credential': forms.PasswordInput(render_value=True),
            'initiator_password': forms.PasswordInput(render_value=True),
        }

@admin.register(MpesaSettings)
class MpesaSettingsAdmin(admin.ModelAdmin):
    form = MpesaSettingsForm
    list_display = ('integration', 'short_code', 'base_url', 'callback_base_url')
    search_fields = ('integration__name', 'short_code', 'base_url', 'callback_base_url')
    list_filter = ('short_code',)


@admin.register(CardPaymentSettings)
class CardPaymentSettingsAdmin(admin.ModelAdmin):
    list_display = ('integration', 'provider', 'is_test_mode', 'default_currency')
    list_filter = ('provider', 'is_test_mode')
    search_fields = ('provider', 'business_name')
    raw_id_fields = ('integration',)


@admin.register(PayPalSettings)
class PayPalSettingsAdmin(admin.ModelAdmin):
    list_display = ('integration', 'is_test_mode', 'business_name', 'default_currency')
    list_filter = ('is_test_mode',)
    search_fields = ('business_name', 'business_email')
    raw_id_fields = ('integration',)


@admin.register(KRASettings)
class KRASettingsAdmin(admin.ModelAdmin):
    list_display = ('mode', 'kra_pin', 'base_url', 'updated_at')
    list_filter = ('mode',)
    search_fields = ('kra_pin', 'device_serial', 'pos_serial')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(KRACertificateRequest)
class KRACertificateRequestAdmin(admin.ModelAdmin):
    list_display = ('cert_type', 'period', 'status', 'requested_by', 'created_at')
    list_filter = ('cert_type', 'status', 'created_at')
    search_fields = ('period',)
    raw_id_fields = ('requested_by',)
    ordering = ('-created_at',)


@admin.register(KRAComplianceCheck)
class KRAComplianceCheckAdmin(admin.ModelAdmin):
    list_display = ('kra_pin', 'is_compliant', 'checked_by', 'created_at')
    list_filter = ('is_compliant', 'created_at')
    search_fields = ('kra_pin',)
    raw_id_fields = ('checked_by',)
    ordering = ('-created_at',)


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'url')
    ordering = ('name',)


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'endpoint', 'status', 'attempts', 'created_at')
    list_filter = ('event_type', 'status', 'created_at')
    search_fields = ('event_type',)
    raw_id_fields = ('endpoint',)
    ordering = ('-created_at',)


@admin.register(BankAPISettings)
class BankAPISettingsAdmin(admin.ModelAdmin):
    list_display = ('bank_name', 'bank_provider', 'is_test_mode', 'is_active', 'created_at')
    list_filter = ('bank_provider', 'is_test_mode', 'is_active')
    search_fields = ('bank_name', 'bank_code', 'account_number')
    raw_id_fields = ('integration',)
    ordering = ('bank_name',)
    
    fieldsets = (
        ('Bank Information', {
            'fields': ('integration', 'bank_provider', 'bank_name', 'bank_code')
        }),
        ('Environment', {
            'fields': ('is_test_mode', 'base_url', 'sandbox_url')
        }),
        ('Credentials (Encrypted)', {
            'fields': ('client_id', 'client_secret', 'api_key', 'api_secret'),
            'classes': ('collapse',)
        }),
        ('Organization', {
            'fields': ('organization_id', 'account_number')
        }),
        ('API Endpoints', {
            'fields': ('auth_path', 'account_balance_path', 'account_statement_path', 
                      'transfer_path', 'bulk_payment_path', 'payment_status_path'),
            'classes': ('collapse',)
        }),
        ('Webhooks', {
            'fields': ('webhook_url', 'callback_url'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )


@admin.register(GovernmentServiceSettings)
class GovernmentServiceSettingsAdmin(admin.ModelAdmin):
    list_display = ('service_name', 'service_provider', 'is_test_mode', 'is_active', 'created_at')
    list_filter = ('service_provider', 'is_test_mode', 'is_active')
    search_fields = ('service_name', 'service_code', 'organization_code')
    ordering = ('service_name',)
    
    fieldsets = (
        ('Service Information', {
            'fields': ('service_provider', 'service_name', 'service_code')
        }),
        ('Environment', {
            'fields': ('is_test_mode', 'base_url', 'sandbox_url')
        }),
        ('Credentials (Encrypted)', {
            'fields': ('client_id', 'client_secret', 'api_key', 'api_token', 'username', 'password'),
            'classes': ('collapse',)
        }),
        ('Organization', {
            'fields': ('organization_id', 'organization_code')
        }),
        ('API Endpoints', {
            'fields': ('auth_path', 'query_path', 'submit_path', 'status_path'),
            'classes': ('collapse',)
        }),
        ('Webhooks', {
            'fields': ('webhook_url', 'callback_url'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )
