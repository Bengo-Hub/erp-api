from django.contrib import admin
from .models import *

@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    pass

# CompanyDetails is deprecated in favor of business.Bussiness
class BankBranchesInline(admin.StackedInline):
    model = BankBranches
    extra = 1

@admin.register(BankBranches)
class BankBranchesAdmin(admin.ModelAdmin):
    list_display = ('bank','name', 'code')
    search_fields = ('bank','name', 'code')
    list_filter = ('bank','name', 'code')

@admin.register(BankInstitution)
class BankInstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'short_code', 'country', 'is_active')
    search_fields = ('name', 'code', 'short_code', 'country')
    list_filter = ('is_active', 'country')
    inlines = [BankBranchesInline]

# Legacy alias for backward compatibility
Banks = BankInstitution
BanksAdmin = BankInstitutionAdmin

@admin.register(Regions)
class RegionsAdmin(admin.ModelAdmin):
    pass

@admin.register(Projects)
class ProjectsAdmin(admin.ModelAdmin):
    pass

@admin.register(ProjectCategory)
class ProjectCategoryAdmin(admin.ModelAdmin):
    pass

@admin.register(Departments)
class DepartmentsAdmin(admin.ModelAdmin):
    pass

@admin.register(ContractSetting)
class ContractSettingAdmin(admin.ModelAdmin):
    pass

# OvertimeRate and PartialMonthPay admin removed - use GeneralHRSettings instead
# See: hrm.payroll_settings.admin.GeneralHRSettingsAdmin

@admin.register(RegionalSettings)
class RegionalSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'timezone', 'date_format', 'currency', 'currency_symbol', 'financial_year_end')
    fieldsets = (
        ('Timezone & Date', {
            'fields': ('timezone', 'date_format', 'financial_year_end')
        }),
        ('Currency', {
            'fields': ('currency', 'currency_symbol')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('created_at', 'updated_at')
    
    def has_add_permission(self, request):
        """Prevent adding more than one instance"""
        return not RegionalSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion"""
        return False


@admin.register(BrandingSettings)
class BrandingSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'app_name', 'primary_color', 'secondary_color', 'enable_dark_mode', 'theme_preset')
    fieldsets = (
        ('Application Identity', {
            'fields': ('app_name', 'tagline', 'footer_text')
        }),
        ('Logos & Images', {
            'fields': ('logo', 'logo_url', 'watermark', 'watermark_url', 'favicon_url')
        }),
        ('Color Palette', {
            'fields': ('primary_color', 'secondary_color', 'text_color', 'background_color')
        }),
        ('Theme', {
            'fields': ('enable_dark_mode', 'theme_preset', 'menu_mode')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('created_at', 'updated_at')
    
    def has_add_permission(self, request):
        """Prevent adding more than one instance"""
        return not BrandingSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion"""
        return False
