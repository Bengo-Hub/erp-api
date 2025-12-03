from django.contrib import admin
from .models import Quotation, QuotationEmailLog


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ['quotation_number', 'customer', 'quotation_date', 'valid_until', 'status', 'total', 'is_converted']
    list_filter = ['status', 'is_converted', 'quotation_date', 'valid_until']
    search_fields = ['quotation_number', 'customer__user__first_name', 'customer__user__last_name', 'customer__business_name']
    readonly_fields = ['quotation_number', 'order_number', 'sent_at', 'viewed_at', 'accepted_at', 'declined_at', 'is_converted', 'converted_at', 'converted_by']
    date_hierarchy = 'quotation_date'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('quotation_number', 'customer', 'branch', 'quotation_date', 'valid_until', 'status')
        }),
        ('Validity', {
            'fields': ('validity_period', 'custom_validity_days')
        }),
        ('Financial Details', {
            'fields': ('subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total', 'discount_type', 'discount_value')
        }),
        ('Email & Tracking', {
            'fields': ('sent_at', 'viewed_at', 'accepted_at', 'declined_at', 'follow_up_date', 'reminder_sent')
        }),
        ('Content', {
            'fields': ('introduction', 'customer_notes', 'terms_and_conditions')
        }),
        ('Conversion', {
            'fields': ('is_converted', 'converted_at', 'converted_by')
        }),
    )


@admin.register(QuotationEmailLog)
class QuotationEmailLogAdmin(admin.ModelAdmin):
    list_display = ['quotation', 'email_type', 'recipient_email', 'status', 'sent_at', 'opened_at']
    list_filter = ['email_type', 'status', 'sent_at']
    search_fields = ['quotation__quotation_number', 'recipient_email']
    readonly_fields = ['quotation', 'email_type', 'recipient_email', 'sent_at', 'opened_at', 'clicked_at', 'status']
    date_hierarchy = 'sent_at'
