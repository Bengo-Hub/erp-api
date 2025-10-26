from django.contrib import admin
from .models import *
from django.contrib.contenttypes.models import ContentType

class FormulaItemsInline(admin.TabularInline):
    model = FormulaItems
    extra = 0


class FormulaSplitRationInline(admin.TabularInline):
    model = SplitRatio
    extra = 0


# Approval admin registration removed - Approval is now registered in centralized approvals app


@admin.register(RepayOption)
class RepayOptionAdmin(admin.ModelAdmin):
    list_display = ('amount', 'no_of_installments','installment_amount')
    list_filter =  ('amount', 'no_of_installments','installment_amount')
    search_fields =  ('amount', 'no_of_installments','installment_amount')
    readonly_fields=["installment_amount",]

    
@admin.register(Formulas)
class FormulaAdmin(admin.ModelAdmin):
    inlines = [FormulaItemsInline,FormulaSplitRationInline]
    list_display= ('type','deduction', 'category', 'title', 'unit', 'effective_from', 'effective_to','upper_limit', 'upper_limit_amount','upper_limit_percentage','personal_relief','relief_carry_forward','progressive','is_current')
    fieldsets = (
        (None, {
            'fields': ('type','deduction', 'category', 'title', 'unit', 'effective_from', 'effective_to','upper_limit', 'upper_limit_amount','upper_limit_percentage','personal_relief','relief_carry_forward','progressive','is_current')
        }),
    )
    list_display_links=['title']
    list_editable=['is_current', 'effective_from', 'effective_to','upper_limit', 'upper_limit_amount','upper_limit_percentage','personal_relief','relief_carry_forward','progressive','is_current']

class CategoryFilter(admin.SimpleListFilter):
    title = 'category'
    parameter_name = 'category'

    def lookups(self, request, model_admin):
        return PayrollComponents.CATEGORY_CHOICES

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(category=self.value())
        return queryset

@admin.register(PayrollComponents)
class PayrollComponentsAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('title','mode', 'non_cash', 'deduct_after_taxing', 'applicable_relief', 'checkoff', 'constant', 'statutory', 'is_active', 'taxable_status')
    list_filter = (CategoryFilter, 'mode', 'statutory', 'is_active')
    search_fields = ('title','mode', 'non_cash', 'deduct_after_taxing', 'applicable_relief', 'checkoff', 'constant', 'statutory', 'is_active', 'taxable_status')
    list_display_links=['title']
    list_editable=['mode', 'non_cash', 'deduct_after_taxing', 'applicable_relief', 'checkoff', 'constant', 'statutory', 'is_active', 'taxable_status']
    ordering = ('category', 'title')
    fieldsets = (
        ('General Information', {
            'fields': ('wb_code', 'acc_code', 'title', 'category', 'description')
        }),
        ('Payroll Configuration', {
            'fields': ('mode', 'non_cash', 'deduct_after_taxing', 'applicable_relief', 'checkoff', 'constant', 'statutory', 'is_active', 'taxable_status')
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by('category', 'title')
    
@admin.register(Loans)
class LoansAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('title', 'wb_code', 'account_code', 'is_active', 'round_off')
    list_filter = ('title', 'wb_code', 'account_code', 'is_active')
    search_fields =  ('title', 'wb_code', 'account_code', 'is_active')

@admin.register(DefaultPayrollSettings)
class DefaultPayrollSettingsAdmin(admin.ModelAdmin):
    list_per_page=10
    # list_display = ('deductions', 'benefits', 'earnings')
    # list_filter = ('deductions', 'benefits', 'earnings')
    # search_fields = ('deductions', 'benefits', 'earnings')
@admin.register(BenefitTaxes)
class BenefitTaxesAdmin(admin.ModelAdmin):
    # Display these fields in the list view
    list_display = ('title', 'actual_amount', 'fixed_limit', 'percentage', 'percent_of', 'amounts_greater_than')
    
    # Add a search bar for the 'title' field
    search_fields = ('title',)
    
    # Add filters for the 'actual_amount' and 'percent_of' fields
    list_filter = ('actual_amount', 'percent_of')
    
    # Customize the form layout
    fieldsets = (
        (None, {
            'fields': ('title', 'actual_amount')
        }),
        ('Limits', {
            'fields': ('fixed_limit', 'percentage', 'percent_of', 'amounts_greater_than'),
        }),
    )

@admin.register(GeneralHRSettings)
class GeneralHRSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'overtime_normal_days', 'overtime_non_working_days', 'overtime_holidays', 
                    'partial_months', 'allow_backwards_payroll')
    fieldsets = (
        ('Overtime Rates', {
            'fields': ('overtime_normal_days', 'overtime_non_working_days', 'overtime_holidays')
        }),
        ('Payroll Configuration', {
            'fields': ('partial_months', 'round_off_currency', 'round_off_amount', 'allow_backwards_payroll')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('created_at', 'updated_at')
    
    def has_add_permission(self, request):
        """Prevent adding more than one instance"""
        return not GeneralHRSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion"""
        return False

@admin.register(Relief)
class ReliefAdmin(admin.ModelAdmin):
    list_display=['type','title','actual_amount','fixed_limit','percentage','percent_of','is_active']
    list_filter=['type','title','actual_amount','fixed_limit','percentage','percent_of','is_active']
    list_editable=['title','actual_amount','fixed_limit','percentage','percent_of','is_active']
    list_display_links=['type']

admin.site.register(WithHoldingtax)
admin.site.register([MarketLengingRates])