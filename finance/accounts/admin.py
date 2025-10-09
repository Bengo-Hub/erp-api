from django.contrib import admin
from .models import *

@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ('reference_number', 'voucher_type', 'amount', 'currency', 'voucher_date', 'status')
    list_filter = ('status', 'voucher_type', 'voucher_date')
    search_fields = ('reference_number', 'remarks')
    readonly_fields = ('voucher_date', 'reference_number', 'status')
    ordering = ['-voucher_date']

@admin.register(VoucherItem)
class VoucherItemAdmin(admin.ModelAdmin):
    list_display = ('voucher', 'description', 'quantity', 'unit_price', 'amount')
    list_filter = ('voucher',)
    search_fields = ('description',)
    ordering = ['voucher']

@admin.register(VoucherAudit)
class VoucherAuditAdmin(admin.ModelAdmin):
    list_display = ('voucher', 'action', 'action_by', 'action_date')
    list_filter = ('action', 'action_date')
    search_fields = ('voucher__reference_number', 'remarks')
    readonly_fields = ('action_date', 'action_by')
    ordering = ['-action_date']


admin.site.register(AccountTypes)

@admin.register(PaymentAccounts)
class PaymentAccountsAdmin(admin.ModelAdmin):
    list_display = ['name', 'account_number', 'account_type', 'opening_balance']
    search_fields = ['name', 'account_number', 'account_type__name']
    list_filter = ['account_type']
    fieldsets = (
        (None, {
            'fields': ('name', 'account_number', 'account_type', 'opening_balance')
        }),
    )

@admin.register(TransactionPayment)
class TransactionPaymentAdmin(admin.ModelAdmin):
    list_display = ('transaction_type', 'ref_no', 'amount_paid', 'payment_account', 'paid_by', 'payment_date')
    list_filter = ('transaction_type', 'payment__payment_method', 'payment_date')
    search_fields = ('transaction_id',)
    date_hierarchy = 'payment_date'
    #readonly_fields = ('transaction_type', 'ref_no', 'amount_paid', 'payment_method', 'payment_account', 'paid_by', 'payment_date')


