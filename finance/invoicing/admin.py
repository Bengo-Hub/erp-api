from django.contrib import admin
from .models import Invoice, InvoicePayment, InvoiceEmailLog


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'customer', 'invoice_date', 'due_date', 'status', 'total', 'amount_paid', 'balance_due']
    list_filter = ['status', 'invoice_date', 'due_date', 'payment_gateway_enabled', 'is_recurring']
    search_fields = ['invoice_number', 'customer__user__first_name', 'customer__user__last_name', 'customer__business_name']
    readonly_fields = ['invoice_number', 'order_number', 'sent_at', 'viewed_at', 'approved_by', 'approved_at', 'balance_due']
    date_hierarchy = 'invoice_date'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('invoice_number', 'customer', 'branch', 'invoice_date', 'due_date', 'status')
        }),
        ('Payment Terms', {
            'fields': ('payment_terms', 'custom_terms_days', 'payment_gateway_enabled', 'payment_gateway_name', 'payment_link')
        }),
        ('Financial Details', {
            'fields': ('subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total', 'amount_paid', 'balance_due')
        }),
        ('Email & Scheduling', {
            'fields': ('sent_at', 'viewed_at', 'last_reminder_sent', 'reminder_count', 'is_scheduled', 'scheduled_send_date')
        }),
        ('Template & Notes', {
            'fields': ('template_name', 'customer_notes', 'terms_and_conditions')
        }),
        ('Approval', {
            'fields': ('requires_approval', 'approval_status', 'approved_by', 'approved_at')
        }),
        ('Recurring', {
            'fields': ('is_recurring', 'recurring_interval', 'next_invoice_date')
        }),
        ('Links', {
            'fields': ('quotation',)
        }),
    )


@admin.register(InvoicePayment)
class InvoicePaymentAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'amount', 'payment_account', 'payment_date', 'created_at']
    list_filter = ['payment_date', 'payment_account']
    search_fields = ['invoice__invoice_number', 'notes']
    date_hierarchy = 'payment_date'


@admin.register(InvoiceEmailLog)
class InvoiceEmailLogAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'email_type', 'recipient_email', 'status', 'sent_at', 'opened_at']
    list_filter = ['email_type', 'status', 'sent_at']
    search_fields = ['invoice__invoice_number', 'recipient_email']
    readonly_fields = ['invoice', 'email_type', 'recipient_email', 'sent_at', 'opened_at', 'clicked_at', 'status']
    date_hierarchy = 'sent_at'
