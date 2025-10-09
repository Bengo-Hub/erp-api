from django.contrib import admin

from business.models import Bussiness
from .models import*
from django.db.models import Q


@admin.register(Payslip)
class PayslippAdmin(admin.ModelAdmin):
    list_per_page=10
    date_hierarchy = 'payment_period'
    # Fields to display in the admin list view
    list_display = (
        'employee', 'payment_period','payroll_status', 'gross_pay', 'net_pay', 
        'nssf_employee_tier_1', 'nssf_employee_tier_2', 'nssf_employer_contribution',
        'taxable_pay', 'paye', 'period_start', 'period_end'
    )
    list_filter = ('payment_period', 'employee','payroll_status')
    search_fields = ('employee__username','payroll_status', 'employee__email', 'payment_period')
    readonly_fields = ('payroll_date','period_start', 'period_end')
    
    # Fields to display when viewing a specific record
    fieldsets = (
        ('Employee Info', {
            'fields': ('employee', 'payment_period')
        }),
        ('Payroll Details', {
            'fields': (
                'gross_pay', 'net_pay', 'nssf_employee_tier_1', 'nssf_employee_tier_2', 
                'nssf_employer_contribution', 'nhif_contribution', 'housing_levy', 
                'tax_relief', 'taxable_pay', 'reliefs', 'paye',
                'gross_pay_after_tax', 'deductions_before_tax', 'deductions_after_tax', 
                'deductions_after_paye', 'deductions_final', 'total_earnings'
            )
        }),
        ('Approval', {
            'fields': ('approver', 'approval_status')
        }),
        ('Timestamps', {
            'fields': ('payroll_date','period_start', 'period_end')
        }),
    )

    # Ordering the records
    ordering = ('-payment_period',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(getattr(request.user, "employee", None), "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs


@admin.register(PayslipAudit)
class PayslipAuditAdmin(admin.ModelAdmin):
    list_display = ('payslip', 'action', 'action_by', 'action_date', 'remarks')
    list_filter = ('action', 'action_date', 'action_by')
    search_fields = ('payslip__id', 'action_by__username', 'remarks')
    ordering = ('-action_date',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(getattr(request.user, "employee", None), "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(payslip__employee__organisation__in=owner_businesses)
        ).distinct()
        return qs
