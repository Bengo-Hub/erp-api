from django.contrib import admin
from .models import Payment, PaymentMethod, BillingDocument, PaymentTransaction, PaymentRefund

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['reference_number', 'amount', 'payment_method', 'status', 'created_at']
    list_filter = ['payment_method', 'status', 'created_at']
    search_fields = ['reference_number', 'transaction_id', 'notes']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'code']

@admin.register(BillingDocument)
class BillingDocumentAdmin(admin.ModelAdmin):
    list_display = ['document_number', 'document_type', 'status', 'customer', 'total', 'issue_date']
    list_filter = ['document_type', 'status', 'issue_date']
    search_fields = ['document_number', 'customer__name']

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ['payment', 'transaction_type', 'amount', 'status', 'created_at']
    list_filter = ['transaction_type', 'status', 'created_at']
    search_fields = ['payment__reference_number', 'transaction_id']

@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = ['payment', 'amount', 'reason', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['payment__reference_number', 'refund_reference']
