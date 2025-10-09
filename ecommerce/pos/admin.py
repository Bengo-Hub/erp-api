from django.contrib import admin
from .models import *
from business.models import Branch
from django.utils.translation import gettext_lazy as _

@admin.register(Register)
class RegisterAdmin(admin.ModelAdmin):
    list_display = ('id', 'opened_at', 'closed_at', 'cash_at_opening', 'cash_at_closing', 'total_sales', 'total_expenses', 'is_open')
    list_filter = ('opened_at', 'closed_at', 'is_open')
    search_fields = ('id','cash_at_opening',)
    #date_hierarchy = 'opened_at'
    readonly_fields = ('total_sales', 'total_expenses')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter registers based on the obtained branches
            qs = qs.filter(branch__in=branches)
        return qs

class SalesItemsInline(admin.TabularInline):
    model = salesItems
    extra=0

@admin.register(Sales)
class SalesAdmin(admin.ModelAdmin):
    list_per_page = 10
    #date_hierarchy = 'date_added'
    list_display = ('sale_id','sale_source','customer', 'sub_total', 'grand_total', 'balance_due','balance_overdue','payment_status','status', 'paymethod','attendant', 'date_added', 'date_updated')
    list_filter = ('status','payment_status', 'paymethod',  'attendant')
    search_fields = ('sale_id', 'payment_status','status', 'paymethod',  'attendant__username')
    list_editable=['sub_total','sale_source','customer','grand_total', 'payment_status','status', 'paymethod',  'attendant',]
    list_display_links=['sale_id']
    inlines = [SalesItemsInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter sales based on the obtained branches
            qs = qs.filter(register__branch__in=branches)
        return qs

@admin.register(SalesLogs)
class SaleLogsAdmin(admin.ModelAdmin):
    list_per_page = 10

class ShippingDocumentsInline(admin.TabularInline):
    model = ShippingDocuments
    extra = 0

@admin.register(Shipping)
class ShippingAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ['id', 'shipping_address', 'status', 'delivered_to']
    search_fields = ['id', 'shipping_address__address']
    list_filter = ['status']
    inlines = [ShippingDocumentsInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter shipping based on the obtained branches
            qs = qs.filter(sale__register__branch__in=branches)
        return qs

@admin.register(ShippingDocuments)
class ShippingDocumentsAdmin(admin.ModelAdmin):
    list_per_page = 10

@admin.register(PayTerm)
class PayTermAdmin(admin.ModelAdmin):
    list_per_page = 10

class ReturnedItemInline(admin.TabularInline):
    model = ReturnedItem
    extra = 0

@admin.register(SalesReturn)
class SalesReturnAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ('original_sale', 'return_id','reason', 'date_returned')
    inlines = [ReturnedItemInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter sales returns based on the obtained branches
            qs = qs.filter(original_sale__register__branch__in=branches)
        return qs

@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ('transactionRef', 'clientName',
                    'clientId', 'transactionType','amount', )
    list_editable = ['clientName', 'clientId', 'transactionType','amount',]
    list_display_links = ['transactionRef']  # Choose a field for editing links
    list_filter = ('clientName', 'clientId', 'transactionType',
                   'transactionRef', 'amount', )
    search_fields= ('clientName', 'clientId', 'transactionType', 'transactionRef','amount', )

@admin.register(POSAdvanceSaleRecord)
class POSAdvanceSaleRecordAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ('reference_id', 'sale', 'advance', 'date_created', 'created_by')
    list_filter = ('date_created', 'created_by')
    search_fields = ('reference_id', 'sale__sale_id', 'advance__employee__user__username')
    readonly_fields = ('reference_id', 'date_created')
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter records based on the obtained branches
            qs = qs.filter(sale__register__branch__in=branches)
        return qs

