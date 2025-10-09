from django.contrib import admin
from .models import *
from django.db.models import Q
from business.models import Branch
from django.contrib.auth import get_user_model
User = get_user_model()
# Register your models here.

class VariationImagesInline(admin.TabularInline):
    model = VariationImages
    extra = 0

@admin.register(Discounts)
class DiscountsAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ['name', 'discount_type', 'percentage', 'discount_amount', 'start_date', 'end_date']
    list_filter = ['discount_type', 'start_date', 'end_date']
    search_fields = ['name', 'discount_type', 'percentage', 'discount_amount']
    list_editable = ['discount_type', 'percentage', 'discount_amount', 'start_date', 'end_date']
    list_display_links = ['name']
    

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_per_page = 10
    

@admin.register(Favourites)
class FavouritesAdmin(admin.ModelAdmin):
    list_per_page = 10
    
@admin.register(Variations)
class VariationsAdmin(admin.ModelAdmin):
    inlines=[VariationImagesInline]
    list_display = ['title','stock_item','serial', 'sku']
    list_filter = ['title','stock_item','sku','serial']
    search_fields = ['title','stock_item','serial', 'sku']

    def get_queryset(self,request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter expenses based on the obtained branches
            qs = qs.filter(stock__branch__in=branches)
        return qs   

@admin.register(StockInventory)
class StockInventoryAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = (
        'product','product_type','variation','manufacturing_cost','buying_price', 'selling_price','branch','stock_level', 'reorder_level','unit', 'availability',
        'is_new_arrival','is_top_pick','is_raw_material'
    )
    list_editable = ['branch','buying_price', 'selling_price','product_type','stock_level','reorder_level','unit', 'availability',
                     'is_new_arrival','is_top_pick','is_raw_material']
    list_display_links = ['product']  # Choose a field for editing links

    list_filter = ('branch','product__title','variation__title', 'selling_price','unit__title','availability','is_new_arrival','is_top_pick','is_raw_material')
    search_fields = ('branch','product__title','variation__title', 'selling_price','unit__title','is_raw_material')

    fieldsets = [
        ('Product Information', {
            'fields': ['branch','product','product_type', 'stock_level', 'reorder_level','unit','manufacturing_cost','buying_price', 'selling_price'],
        }),
        ('Additional Information', {
            'fields': ['applicable_tax','discount','usage','supplier'],
        }),
        ('Availability and Promotions', {
            'fields': ['availability', 'is_new_arrival','is_top_pick','is_raw_material'],
        }),
        ('Variations', {
            'fields': ['variation',],
        }),
    ]

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
            # Filter expenses based on the obtained branches
            qs = qs.filter(branch__in=branches)
        return qs
    
@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_per_page = 20
    list_display = ['transaction_type', 'transaction_date', 'stock_item', 'quantity']
    list_filter = ['transaction_type', 'transaction_date','transaction_type']
    search_fields = ['stock_item','transaction_date','transaction_type'] 
    #date_hierarchy='transaction_date'

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
            # Filter expenses based on the obtained branches
            qs = qs.filter(branch__in=branches)
        return qs

# Define the admin class for StockTransferItem
class StockTransferItemInline(admin.TabularInline):
    model = StockTransferItem
    extra = 0

@admin.register(StockTransferItem)
class StockTransferItemAdmin(admin.ModelAdmin):
    list_per_page = 20
    list_display = ('id', 'stock_transfer', 'stock_item')
    list_filter =  ('id', 'stock_transfer', 'stock_item')
    search_fields =  ('id', 'stock_transfer', 'stock_item')
    list_editable= ('stock_item',)
    list_display_links=['id']

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
            # Filter expenses based on the obtained branches
            qs = qs.filter(Q(stock_transfer__branch_from__in=branches)|Q(stock_transfer__branch_to__in=branches))
        return qs

@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_per_page = 20
    list_display = ('id','added_by','transfrer_date', 'ref_no', 'status', 'branch_from', 'branch_to', 'transfer_shipping_charge','net_total','purchase_total')
    list_filter = ('status', 'branch_from', 'branch_to','net_total','purchase_total')
    search_fields = ('transfrer_date','ref_no','branch_from','branch_to','net_total','purchase_total')
    list_editable=('ref_no', 'status', 'branch_from', 'branch_to', 'transfer_shipping_charge','net_total','purchase_total')
    list_display_links=['id','transfrer_date']
    inlines = [StockTransferItemInline]
    #date_hierarchy='transfrer_date'

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['added_by'].queryset = User.objects.filter(Q(is_staff=True)|Q(role__name__in=['staff','manager','cashier']))
        form.base_fields['added_by'].initial = request.user
        return form

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
            # Filter expenses based on the obtained branches
            qs = qs.filter(Q(branch_from__in=branches)|Q(branch_to__in=branches))
        return qs
    
@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_per_page = 20
    list_display = ('id','adjusted_at','branch','stock_item','adjustment_type', 'quantity_adjusted', 'adjusted_by')
    list_filter = ('adjustment_type', 'adjusted_at')
    search_fields = ('stock_item', 'adjusted_by__username')
    #date_hierarchy = 'adjusted_at'
    readonly_fields = ('adjusted_at',)
    list_editable=('stock_item','branch','adjustment_type', 'quantity_adjusted', 'adjusted_by')
    list_display_links=['id','adjusted_at']

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['adjusted_by'].queryset = User.objects.filter(Q(is_staff=True)|Q(role__name__in=['staff','manager','cashier']))
        form.base_fields['adjusted_by'].initial = request.user
        return form

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
            # Filter expenses based on the obtained branches
            qs = qs.filter(Q(stock_item__branch__in=branches))
        return qs

@admin.register(ProductView)
class ProductViewAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ['stock', 'viewed_by']
    list_filter = ['stock']
    search_fields = ['stock__product__title']
    list_editable = ['viewed_by']
    list_display_links = ['stock']

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ['user', 'stock', 'rating', 'text', 'created_at']
    list_filter = ['user', 'stock', 'rating']
    search_fields = ['user__username', 'stock__product__title', 'text']
    list_editable = ['rating', 'text']
    list_display_links = ['user', 'stock']

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
            # Filter expenses based on the obtained branches
            qs = qs.filter(Q(stock_item__branch__in=branches))
        return qs

@admin.register(VariationImages)
class VariationImagesAdmin(admin.ModelAdmin):
    list_per_page = 10
    



