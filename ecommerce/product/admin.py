from django.contrib import admin
from django.contrib import messages
from .models import *
from django.db.models import Sum
from business.models import Branch, Bussiness
from django import forms
from ecommerce.stockinventory.models import StockInventory

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

class ProductAdminForm(forms.ModelForm):
    """Custom form for Products with additional stock fields for batch editing."""
    # Stock-related fields for quick editing (only for goods)
    stock_level = forms.IntegerField(required=False, min_value=0, help_text='Current stock level (goods only)')
    buying_price = forms.DecimalField(required=False, max_digits=14, decimal_places=2, help_text='Buying price')
    selling_price_field = forms.DecimalField(required=False, max_digits=14, decimal_places=2, help_text='Selling price')
    reorder_level = forms.IntegerField(required=False, min_value=0, help_text='Reorder level')

    class Meta:
        model = Products
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-populate stock fields if editing existing product
        if self.instance and self.instance.pk:
            stock = self.instance.stock.first()
            if stock:
                self.fields['stock_level'].initial = stock.stock_level
                self.fields['buying_price'].initial = stock.buying_price
                self.fields['selling_price_field'].initial = stock.selling_price
                self.fields['reorder_level'].initial = stock.reorder_level


@admin.register(Products)
class ProductsAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_per_page = 25
    inlines = [ProductImagesInline]
    list_display = [
        'id', 'title', 'sku', 'serial', 'product_type', 'default_price', 'selling_price', 'total_stock', 'availability',
        'category', 'brand', 'model', 'business', 'status', 'is_featured', 'is_manufactured', 'weight', 'dimentions', 'updated_at'
    ]
    list_filter = ['product_type', 'status', 'category', 'brand', 'model', 'business', 'is_featured', 'is_manufactured']
    search_fields = ['title', 'sku', 'serial', 'description', 'category__name', 'brand__title', 'model__title', 'business__name']
    list_editable = ['title', 'sku', 'serial', 'product_type', 'default_price', 'category', 'brand', 'model', 'business', 'status', 'is_featured', 'is_manufactured', 'weight', 'dimentions']
    list_display_links = ['id']
    ordering = ['-updated_at']
    date_hierarchy = 'created_at'
    actions = [
        'set_status_active', 'set_status_inactive',
        'set_featured', 'unset_featured',
        'set_product_type_goods', 'set_product_type_service',
        'assign_to_business', 'assign_to_category',
        'create_stock_entries'
    ]

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'sku', 'serial', 'description', 'product_type', 'status'),
            'classes': ('wide',)
        }),
        ('Classification', {
            'fields': ('category', 'brand', 'model'),
            'classes': ('wide',)
        }),
        ('Pricing', {
            'fields': ('default_price',),
            'classes': ('wide',)
        }),
        ('Stock Information (Goods Only)', {
            'fields': ('stock_level', 'buying_price', 'selling_price_field', 'reorder_level'),
            'classes': ('collapse', 'wide'),
            'description': 'These fields update the first stock entry for this product. For goods only.'
        }),
        ('Physical Attributes', {
            'fields': ('weight', 'dimentions'),
            'classes': ('collapse', 'wide')
        }),
        ('Business & Ownership', {
            'fields': ('business',),
            'classes': ('wide',)
        }),
        ('Flags', {
            'fields': ('is_featured', 'is_manufactured'),
            'classes': ('wide',)
        }),
        ('SEO', {
            'fields': ('seo_title', 'seo_description', 'seo_keywords'),
            'classes': ('collapse', 'wide')
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            branches = owned_branches | employee_branches
            qs = qs.filter(stock__branch__in=branches)
        return qs.distinct()

    def save_model(self, request, obj, form, change):
        """Save product and update stock if stock fields were provided."""
        super().save_model(request, obj, form, change)

        # Only update stock for goods
        if obj.product_type == 'goods':
            stock_level = form.cleaned_data.get('stock_level')
            buying_price = form.cleaned_data.get('buying_price')
            selling_price = form.cleaned_data.get('selling_price_field')
            reorder_level = form.cleaned_data.get('reorder_level')

            # Check if any stock field was provided
            if any([stock_level is not None, buying_price is not None, selling_price is not None, reorder_level is not None]):
                stock = obj.stock.first()
                if stock:
                    # Update existing stock
                    if stock_level is not None:
                        stock.stock_level = stock_level
                    if buying_price is not None:
                        stock.buying_price = buying_price
                    if selling_price is not None:
                        stock.selling_price = selling_price
                    if reorder_level is not None:
                        stock.reorder_level = reorder_level
                    stock.save()
                else:
                    # Create new stock entry if business has a branch
                    if obj.business:
                        branch = Branch.objects.filter(business=obj.business, is_main_branch=True).first()
                        if not branch:
                            branch = Branch.objects.filter(business=obj.business, is_active=True).first()
                        if branch:
                            StockInventory.objects.create(
                                product=obj,
                                branch=branch,
                                stock_level=stock_level or 1,
                                buying_price=buying_price or 0,
                                selling_price=selling_price or obj.default_price or 0,
                                reorder_level=reorder_level or 2,
                                product_type='single'
                            )

    def selling_price(self, obj):
        """Return a representative selling price for the product."""
        try:
            stock = obj.stock.first()
            if stock and stock.selling_price:
                return stock.selling_price
        except Exception:
            pass
        return obj.default_price
    selling_price.short_description = 'Selling Price'
    selling_price.admin_order_field = 'stock__selling_price'

    def total_stock(self, obj):
        """Return aggregated stock level across branches."""
        try:
            total = obj.stock.aggregate(total=Sum('stock_level'))['total']
            return total or 0
        except Exception:
            return 0
    total_stock.short_description = 'Total Stock'
    total_stock.admin_order_field = 'stock__stock_level'

    def availability(self, obj):
        """Human friendly availability status."""
        if obj.product_type == 'service':
            return 'Service'
        total = self.total_stock(obj)
        return 'In Stock' if total > 0 else 'Out of Stock'
    availability.short_description = 'Availability'

    # ===== BATCH ACTIONS =====

    @admin.action(description='Set selected products to Active')
    def set_status_active(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f'{updated} product(s) set to Active.', messages.SUCCESS)

    @admin.action(description='Set selected products to Inactive')
    def set_status_inactive(self, request, queryset):
        updated = queryset.update(status='inactive')
        self.message_user(request, f'{updated} product(s) set to Inactive.', messages.SUCCESS)

    @admin.action(description='Mark selected as Featured')
    def set_featured(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f'{updated} product(s) marked as Featured.', messages.SUCCESS)

    @admin.action(description='Unmark selected as Featured')
    def unset_featured(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, f'{updated} product(s) unmarked as Featured.', messages.SUCCESS)

    @admin.action(description='Set type to Goods')
    def set_product_type_goods(self, request, queryset):
        updated = queryset.update(product_type='goods')
        self.message_user(request, f'{updated} product(s) set to Goods type.', messages.SUCCESS)

    @admin.action(description='Set type to Service')
    def set_product_type_service(self, request, queryset):
        # Also remove stock entries for services
        for product in queryset:
            product.stock.all().delete()
        updated = queryset.update(product_type='service')
        self.message_user(request, f'{updated} product(s) set to Service type. Stock entries removed.', messages.SUCCESS)

    @admin.action(description='Assign to Business...')
    def assign_to_business(self, request, queryset):
        """Assign selected products to a specific business. Uses intermediate page."""
        # For simplicity, assign to first business of current user
        if request.user.is_superuser:
            business = Bussiness.objects.first()
        else:
            business = Bussiness.objects.filter(owner=request.user).first()

        if business:
            updated = queryset.update(business=business)
            self.message_user(request, f'{updated} product(s) assigned to {business.name}.', messages.SUCCESS)
        else:
            self.message_user(request, 'No business found to assign products to.', messages.WARNING)

    @admin.action(description='Assign to Category...')
    def assign_to_category(self, request, queryset):
        """Assign selected products to the first category."""
        category = Category.objects.filter(status='active').first()
        if category:
            updated = queryset.update(category=category)
            self.message_user(request, f'{updated} product(s) assigned to category: {category.name}.', messages.SUCCESS)
        else:
            self.message_user(request, 'No active category found.', messages.WARNING)

    @admin.action(description='Create stock entries for Goods without stock')
    def create_stock_entries(self, request, queryset):
        """Create stock entries for goods that don't have any."""
        created_count = 0
        skipped_count = 0

        for product in queryset.filter(product_type='goods'):
            if product.stock.exists():
                skipped_count += 1
                continue

            # Find a branch to create stock at
            branch = None
            if product.business:
                branch = Branch.objects.filter(business=product.business, is_main_branch=True).first()
                if not branch:
                    branch = Branch.objects.filter(business=product.business, is_active=True).first()

            if not branch:
                # Try to find any branch for superuser
                if request.user.is_superuser:
                    branch = Branch.objects.filter(is_active=True).first()
                else:
                    owned = Bussiness.objects.filter(owner=request.user).first()
                    if owned:
                        branch = Branch.objects.filter(business=owned, is_active=True).first()

            if branch:
                StockInventory.objects.create(
                    product=product,
                    branch=branch,
                    stock_level=1,
                    buying_price=0,
                    selling_price=product.default_price or 0,
                    reorder_level=2,
                    product_type='single'
                )
                created_count += 1

        self.message_user(
            request,
            f'Created {created_count} stock entries. Skipped {skipped_count} (already have stock).',
            messages.SUCCESS if created_count > 0 else messages.INFO
        )