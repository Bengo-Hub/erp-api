from django.contrib import admin
from .models import (
    BusinessLocation, Bussiness, Branch, TaxRates, ProductSettings, SaleSettings, 
    ServiceTypes, PrefixSettings, PickupStations, BrandingSettings
)

class LocationInline(admin.StackedInline):
    model = BusinessLocation
    extra = 0

class BranchInline(admin.TabularInline):
    model = Branch
    extra = 1
    fields = ['name', 'branch_code', 'location', 'is_active', 'is_main_branch']

class BrandingSettingsInline(admin.StackedInline):
    model = BrandingSettings
    can_delete = False
    verbose_name_plural = 'Branding Settings'
    fieldsets = (
        ('PrimeVue Theme', {
            'fields': ('primary_color_name', 'surface_name'),
            'description': 'These settings control the PrimeVue theme appearance.'
        }),
        ('Advanced UI Settings', {
            'fields': ('compact_mode', 'ripple_effect', 'border_radius', 'scale_factor'),
            'description': 'Fine-tune the UI appearance and behavior.'
        }),
    )
    max_num = 1  # Limit to one inline form
    min_num = 1  # Ensure at least one form
    
    def has_add_permission(self, request, obj=None):
        # Only allow one branding settings instance per business
        if obj and BrandingSettings.objects.filter(business=obj).exists():
            return False
        return True

@admin.register(BusinessLocation)
class BusinessLocationAdmin(admin.ModelAdmin):
    list_display = ['city','county','constituency','ward','country','state','zip_code','postal_code']
    search_fields = ['city','county','constituency','ward','country','state']
    list_filter = ['country', 'state', 'county', 'is_active']
    list_editable=['county','constituency','ward','country','state','zip_code','postal_code']
    list_display_links=['city']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business locations where the user is either the owner or an employee
            # Since BusinessLocation doesn't have a direct business field, we need to filter through branches
            owned_locations = qs.filter(branches__business__owner=request.user)
            employee_locations = qs.filter(branches__business__employees__user=request.user)
            # Combine the two sets of locations using OR operator
            locations = owned_locations | employee_locations
            # Filter locations based on the obtained businesses
        return locations

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ['name', 'branch_code', 'business', 'location', 'is_active', 'is_main_branch', 'created_at']
    search_fields = ['name', 'branch_code', 'business__name', 'location__city']
    list_filter = ['is_active', 'is_main_branch', 'business', 'location__county']
    list_editable = ['is_active', 'is_main_branch']
    list_display_links = ['name', 'branch_code']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get branches where the user is either the owner or an employee
            owned_branches = qs.filter(business__owner=request.user)
            employee_branches = qs.filter(business__employees__user=request.user)
            # Combine the two sets using OR operator
            branches = owned_branches | employee_branches
            return branches

@admin.register(Bussiness)
class BusinessAdmin(admin.ModelAdmin):
    inlines = [BranchInline, BrandingSettingsInline]
    list_display = ['start_date', 'name', 'owner', 'finacial_year_start_month', 
                    'business_primary_color', 'ui_theme_preset', 'ui_dark_mode']
    search_fields = ['name', 'owner__username', 'owner__email']
    list_filter = ['finacial_year_start_month', 'stock_accounting_method', 'ui_theme_preset', 'ui_dark_mode']
    fieldsets = (
        (None, {
            'fields': ('name', 'owner', 'start_date')
        }),
        ('Financial Details', {
            'fields': ('finacial_year_start_month', 'stock_accounting_method', 'currency')
        }),
        ('Transaction Settings', {
            'fields': ('transaction_edit_days', 'default_profit_margin')
        }),
        ('Logo Settings', {
            'fields': ('logo', 'watermarklogo')
        }),
        ('Basic Branding', {
            'fields': ('business_primary_color', 'business_secondary_color', 'business_text_color', 'business_background_color'),
            'description': 'Basic color settings for your business branding.'
        }),
        ('UI Theme Settings', {
            'fields': ('ui_theme_preset', 'ui_menu_mode', 'ui_dark_mode', 'ui_surface_style'),
            'description': 'Configure the theme appearance for your ERP.'
        })
    )
    list_editable = ['name', 'ui_theme_preset', 'ui_dark_mode']
    list_display_links = ['start_date']
    
    def save_model(self, request, obj, form, change):
        # Save the business model first
        super().save_model(request, obj, form, change)
        
        # Only create BrandingSettings if it doesn't exist yet
        # This prevents conflicts with the inline form
        if not hasattr(obj, 'branding'):
            try:
                BrandingSettings.objects.get(business=obj)
            except BrandingSettings.DoesNotExist:
                BrandingSettings.objects.create(
                    business=obj,
                    primary_color_name='blue',
                    surface_name='slate',
                    compact_mode=False,
                    ripple_effect=True
                )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the businesses where the user is either the owner or an employee
            owned_biz = qs.filter(owner=request.user)
            employee_biz = qs.filter(employees__user=request.user)
            # Combine the two sets using OR operator
            businesses = owned_biz | employee_biz
        return businesses
        
@admin.register(TaxRates)
class TaxRatesAdmin(admin.ModelAdmin):
    list_display = ['business','tax_name', 'tax_number', 'percentage']
    search_fields = ['tax_name', 'tax_number']
    list_filter = ['percentage']
    list_editable=['tax_name', 'percentage']
    list_display_links=['tax_number']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the businesses where the user is either the owner or an employee
            owned_taxes = qs.filter(business__owner=request.user)
            employee_taxes = qs.filter(branches__business__employees__user=request.user)
            # Combine the two sets using OR operator
            taxes = owned_taxes | employee_taxes
        return taxes

@admin.register(ProductSettings)
class ProductSettingsAdmin(admin.ModelAdmin):
    list_display = ['id','business','default_unit', 'enable_warranty', 'enable_product_expiry']
    search_fields = ['default_unit']
    list_filter = ['enable_warranty', 'enable_product_expiry']
    list_editable= ['default_unit', 'enable_warranty', 'enable_product_expiry']
    list_display_links=['id']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the businesses where the user is either the owner or an employee
            owned = qs.filter(business__owner=request.user)
            employees = qs.filter(branches__business__employees__user=request.user)
            # Combine the two sets using OR operator
            settings = owned | employees
        return settings

@admin.register(SaleSettings)
class SaleSettingsAdmin(admin.ModelAdmin):
    list_display = ['business','default_discount', 'default_tax']
    search_fields = ['default_discount']
    list_filter = ['default_tax']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the businesses where the user is either the owner or an employee
            owned = qs.filter(business__owner=request.user)
            employees = qs.filter(branches__business__employees__user=request.user)
            # Combine the two sets using OR operator
            settings = owned | employees
        return settings

@admin.register(PrefixSettings)
class PrefixSettingsAdmin(admin.ModelAdmin):
    list_display = ['id','business','purchase', 'purchase_order', 'purchase_return', 'purchase_requisition', 'stock_transfer', 'sale_return', 'expense', 'business_location']
    search_fields = ['purchase', 'purchase_order', 'purchase_return', 'purchase_requisition', 'stock_transfer', 'sale_return', 'expense', 'business_location']
    list_filter = ['purchase', 'purchase_order', 'purchase_return', 'purchase_requisition', 'stock_transfer', 'sale_return', 'expense', 'business_location']
    list_editable=['purchase', 'purchase_order', 'purchase_return', 'purchase_requisition', 'stock_transfer', 'sale_return', 'expense', 'business_location']
    list_display_links=['id']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the businesses where the user is either the owner or an employee
            owned = qs.filter(business__owner=request.user)
            employees = qs.filter(branches__business__employees__user=request.user)
            # Combine the two sets using OR operator
            settings = owned | employees
        return settings

@admin.register(ServiceTypes)
class ServiceTypesAdmin(admin.ModelAdmin):
    list_display = ['id','business','name', 'description', 'packing_charge_type', 'packing_charge']
    search_fields = ['name', 'description']
    list_filter = ['packing_charge_type']
    fieldsets = (
        (None, {
            'fields': ('business','name', 'description')
        }),
        ('Packing Charge', {
            'fields': ('packing_charge_type', 'packing_charge')
        }),
    )
    list_editable=['name', 'packing_charge_type', 'packing_charge']
    list_display_links=['id']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the businesses where the user is either the owner or an employee
            owned = qs.filter(business__owner=request.user)
            employees = qs.filter(branches__business__employees__user=request.user)
            # Combine the two sets using OR operator
            servicetypes = owned | employees
        return servicetypes

@admin.register(PickupStations)
class PickupStationsAdmin(admin.ModelAdmin):
    list_display = ['business', 'pickup_location', 'region', 'description', 'helpline', 'whatsapp_number']
    search_fields = ['pickup_location', 'description', 'helpline', 'whatsapp_number']
    list_filter = ['region', 'business']
    list_editable = ['pickup_location', 'description', 'helpline', 'whatsapp_number']
    list_display_links = ['business']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get pickup stations where the user is either the owner or an employee
            owned = qs.filter(business__owner=request.user)
            employees = qs.filter(branches__business__employees__user=request.user)
            # Combine the two sets using OR operator
            stations = owned | employees
        return stations

