from django.contrib import admin
from django import forms
from .models import (
    Integrations, MpesaSettings, KRASettings
)
# EmailConfig, EmailTemplate, EmailLog, SMSConfig, SMSTemplate, SMSLog, NotificationConfig moved to centralized notifications app

# Inline admin classes
# EmailConfigInline, SMSConfigInline, NotificationConfigInline moved to centralized notifications app

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
        # Email, SMS, and Notification configurations moved to centralized notifications app
            
        return inlines

# Email, SMS, and Notification admin classes moved to centralized notifications app
# Use: from notifications.admin import EmailConfigurationAdmin, EmailTemplateAdmin, etc.

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


@admin.register(KRASettings)
class KRASettingsAdmin(admin.ModelAdmin):
    list_display = ('mode', 'kra_pin', 'base_url', 'updated_at')
    list_filter = ('mode',)
    search_fields = ('kra_pin', 'device_serial', 'pos_serial')
    readonly_fields = ('created_at', 'updated_at')
