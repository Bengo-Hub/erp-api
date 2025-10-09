from django.contrib import admin
from .models import *

# Register your models here.
# EmailConfigs and EmailLogs moved to centralized notifications app
# Use: from notifications.admin import EmailConfigurationAdmin, EmailLogAdmin

@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    pass

# BannerAdmin moved to centralized campaigns app
# Use: from crm.campaigns.admin import CampaignAdmin

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

@admin.register(OvertimeRate)
class OvertimeRateAdmin(admin.ModelAdmin):
    list_display = ('overtime_type', 'overtime_rate', 'is_active')
    list_filter = ('overtime_type', 'is_active')
    search_fields = ('overtime_type', 'overtime_rate')

@admin.register(PartialMonthPay)
class PartialMonthPayAdmin(admin.ModelAdmin):
    list_display = ('prorate_option', 'carry_forward_prorated_pay', 'apply_for', 'is_active')
    list_filter = ('prorate_option', 'apply_for', 'is_active')
    search_fields = ('prorate_option',)

