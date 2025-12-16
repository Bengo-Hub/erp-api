from django.contrib import admin
from .models import *
from django.db.models import Sum
from business.models import Branch
from django import forms

# Register your models here.
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ['id','name','parent','level','order','status']
    list_filter = ['parent','level','status']
    search_fields = ['name','status']
    list_editable = ['name','parent','level','order','status']
    list_display_links=['id']

@admin.register(ProductBrands)
class ProductBrandsAdmin(admin.ModelAdmin):
    list_per_page = 10

@admin.register(ProductModels)
class ProductModelsAdmin(admin.ModelAdmin):
    list_per_page = 10


class ProductImagesInline(admin.TabularInline):
    model=ProductImages
    extra=1

@admin.register(ProductImages)
class ProductImagesAdmin(admin.ModelAdmin):
    list_per_page = 10

@admin.register(Products)
class ProductsAdmin(admin.ModelAdmin):
    list_per_page = 10
    inlines = [ProductImagesInline]
    list_display = [
        'id', 'title', 'sku', 'serial', 'product_type', 'default_price', 'selling_price', 'total_stock', 'availability',
        'category', 'brand', 'model', 'business', 'status', 'is_manufactured', 'weight', 'dimentions', 'updated_at'
    ]
    list_filter = ['title','sku','serial','category','brand','model','business','status','is_manufactured', 'product_type']
    search_fields = ['title','sku','serial','category__name','brand__title','model__title','business__name','status','is_manufactured']
    list_editable = ['title','sku','serial','category','brand','model','business','status','is_manufactured','weight', 'dimentions']
    list_display_links=['id']

    fieldsets = (
        ('Product Information', {
            'fields': ('category','brand', 'model','title','sku','serial', 'description', 'weight', 'dimentions', 'status')
        }),
        )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        #print(qs)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter products based on the obtained branches
            qs = qs.filter(stock__branch__in=branches)
        return qs

    def selling_price(self, obj):
        """Return a representative selling price for the product (first stock selling price or default price)."""
        try:
            stock = obj.stock.first()
            if stock and stock.selling_price:
                return stock.selling_price
        except Exception:
            pass
        return obj.default_price

    def total_stock(self, obj):
        """Return aggregated stock level across branches."""
        try:
            total = obj.stock.aggregate(total=Sum('stock_level'))['total']
            return total or 0
        except Exception:
            return 0

    def availability(self, obj):
        """Human friendly availability: Service / In Stock / Out of Stock"""
        if obj.product_type == 'service':
            return 'Service'
        total = self.total_stock(obj)
        return 'In Stock' if total > 0 else 'Out of Stock'

    # Allow admin to sort by these computed columns where possible
    selling_price.admin_order_field = 'stock__selling_price'
    total_stock.admin_order_field = 'stock__stock_level'
    availability.admin_order_field = 'stock__availability'