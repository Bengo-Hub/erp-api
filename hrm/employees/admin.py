from django.contrib import admin
from .models import *
from django.db.models import Q
from hrm.payroll.models import *
from django import forms

class DeductionsForm(forms.ModelForm):
    class Meta:
        model = Deductions
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter to only show 'Deductions' category items in payrollcomponents
        self.fields['deduction'].queryset = PayrollComponents.objects.filter(category='Deductions')

class BenefitsForm(forms.ModelForm):
    class Meta:
        model = Benefits
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter to only show 'Benefits' category items in payrollcomponents
        self.fields['benefit'].queryset = PayrollComponents.objects.filter(category='Benefits')

class EarningsForm(forms.ModelForm):
    class Meta:
        model = Earnings
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter to only show 'Earnings' category items in payrollcomponents
        self.fields['earning'].queryset = PayrollComponents.objects.filter(category='Earnings')

class SalaryDetailsInline(admin.StackedInline):
    model = SalaryDetails
    extra=0

class ContactDetailsInline(admin.StackedInline):
    model = ContactDetails
    extra=0

class ContractInline(admin.TabularInline):
    model = Contract
    extra = 0  
    fields = ("contract_start_date", "contract_end_date", "status", "salary", "pay_type")
    readonly_fields = ("contract_duration",)  # Make calculated fields read-only


class NextOfKinInline(admin.TabularInline):
    model = NextOfKin
    extra=0

class DocumentsInline(admin.TabularInline):
    model = Documents
    extra=0

class AdvancesInline(admin.TabularInline):
    model = Advances
    fk_name = 'employee'  # Specify the foreign key relationship
    extra=0

class EmployeeLoansInline(admin.TabularInline):
    model = EmployeLoans
    fk_name = 'employee'  # Specify the foreign key relationship
    extra=0

class ExpenseCategoriesInline(admin.TabularInline):
    model = ClaimItems
    fk_name = 'claim'  # Specify the foreign key relationship
    extra=0

class HRDetailsInline(admin.StackedInline):
    model = HRDetails
    fk_name = 'employee'  # Specify the foreign key relationship
    extra=0

class LossesAndDamagesInline(admin.TabularInline):
    model = LossesAndDamages
    fk_name = 'employee'  # Specify the foreign key relationship
    extra=0

class EmployeeDeductionsInline(admin.TabularInline):
    model = Deductions
    form = DeductionsForm  # Use the custom form
    extra = 0

class EmployeeEarningsInline(admin.TabularInline):
    model = Earnings
    form = EarningsForm  # Use the custom form
    extra = 0

class EmployeeBenefitsInline(admin.TabularInline):
    model = Benefits
    form = BenefitsForm  # Use the custom form
    extra = 0

@admin.register(Deductions)
class DeductionsAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ('id', 'employee', 'deduction', 'paid_to_date','quantity', 'amount')
    form = DeductionsForm  # Use the custom form to filter deductions


@admin.register(Benefits)
class BenefitsAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ('id', 'employee', 'benefit', 'amount')
    form = BenefitsForm  # Use the custom form to filter benefits


@admin.register(Earnings)
class EarningsAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ('id', 'employee', 'earning','quantity','rate', 'amount')
    form = EarningsForm 

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_per_page=10
    date_hierarchy = 'date_of_birth'
    list_display = ('id', 'user', 'organisation', 'gender', 'date_of_birth', 'national_id', 'allow_ess', 'ess_unrestricted_access', 'deleted', 'terminated')
    list_filter=['organisation', 'gender', 'allow_ess', 'ess_unrestricted_access', 'deleted','terminated']
    search_fields=['user__email', 'user__first_name', 'user__last_name', 'national_id', 'pin_no', 'shif_or_nhif_number', 'nssf_no']
    list_editable=['organisation','gender','date_of_birth', 'national_id', 'deleted', 'terminated']
    list_display_links=['user','id']
    inlines = [SalaryDetailsInline, HRDetailsInline, ContractInline,ContactDetailsInline, NextOfKinInline, DocumentsInline, EmployeeLoansInline, EmployeeDeductionsInline,EmployeeEarningsInline,EmployeeBenefitsInline]
    fieldsets = (
        ('Personal Information', {
            'fields': ('user', 'organisation','gender', 'passport_photo', 'date_of_birth', 'residential_status', 'national_id', 'pin_no', 'shif_or_nhif_number', 'nssf_no', 'deleted', 'terminated',)
        }),
        ('ESS Access Control', {
            'fields': ('allow_ess', 'ess_unrestricted_access', 'ess_activated_at', 'ess_last_login'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(organisation__in=owner_businesses)
        ).distinct()

        return qs

@admin.register(SalaryDetails)
class SalaryDetailsAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('id', 'employee', 'employment_type', 'monthly_salary', 'pay_type', 'work_hours', 'work_shift', 'hourly_rate', 'daily_rate', 'income_tax', 'deduct_shif_or_nhif', 'deduct_nssf', 'payment_type', 'bank_account', 'mobile_number')
    list_filter = ('employment_type', 'work_shift', 'pay_type', 'income_tax', 'payment_type')
    search_fields = ('employee__user__first_name', 'employee__user__last_name', 'employee__user__email')
    fieldsets = (
        ('General', {
            'fields': ('employee', 'employment_type', 'monthly_salary', 'pay_type', 'work_hours', 'work_shift', 'hourly_rate', 'daily_rate', 'income_tax', 'deduct_shif_or_nhif', 'deduct_nssf')
        }),
        ('Tax Exemption', {
            'fields': ('tax_excemption_amount', 'excemption_cert_no')
        }),
        ('Payment Options', {
            'fields': ('payment_type', 'bank_account', 'mobile_number')
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs


@admin.register(HRDetails)
class HRDetailsAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('id', 'employee', 'job_or_staff_number', 'job_title', 'department', 'head_of', 'reports_to', 'region', 'project', 'date_of_employment', 'board_director')
    fieldsets = (
        ('Employment Information', {
            'fields': ('employee', 'job_or_staff_number', 'job_title', 'department', 'head_of', 'reports_to', 'region', 'project', 'date_of_employment', 'board_director')
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs

@admin.register(ContactDetails)
class ContactDetailsAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('id', 'employee', 'personal_email', 'country', 'county', 'city', 'zip', 'address', 'mobile_phone', 'official_phone')
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs
    
@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('employee', 'contract_start_date', 'contract_end_date','status', 'pay_type', 'salary', 'contract_duration')
    search_fields = ('employee__user__first_name', 'employee__user__last_name', 'pay_type') 
    list_filter = ('pay_type','status', 'contract_start_date', 'contract_end_date')
    readonly_fields = ('contract_duration',) 
    list_display_links=['employee']
    list_editable=('pay_type','status', 'contract_start_date', 'contract_end_date')
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs
    
@admin.register(NextOfKin)
class NextOfKinAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('id', 'employee', 'name', 'relation', 'phone', 'email')
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs

@admin.register(Documents)
class DocumentsAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('id', 'employee', 'document')

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs

@admin.register(Advances)
class AdvancesAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('id', 'employee', 'approver','is_active','approved','repay_option', 'issue_date', 'prev_payment_date','next_payment_date', 'amount_issued', 'amount_repaid')
    list_display_links=["employee"]
    list_editable=('approver','approved','is_active')
    readonly_fields=["amount_issued","amount_repaid"]
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs

@admin.register(EmployeLoans)
class LoansAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('id', 'employee','principal_amount','no_of_installments_paid','interest_paid','amount_repaid','monthly_installment','interest_rate','fringe_benefit_tax','is_active')
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs
    
@admin.register(LossesAndDamages)
class LossesAndDamagesAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('id', 'employee', 'approver','is_active','approved', 'issue_date', 'next_payment_date', 'damage_amount', 'amount_repaid')
    list_display_links=["employee"]
    list_editable=('approver','approved','is_active')


    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs

@admin.register(ExpenseClaims)
class ExpenseClaimsAdmin(admin.ModelAdmin):
    list_per_page=10
    inlines=[ExpenseCategoriesInline]
    list_display = ('id', 'employee', 'approver','is_active','approved', 'category', 'application_date', 'attachment','is_active','is_paid','schedule_to_payroll','delete_status')
    search_fields=('approver','approved', 'category', 'application_date', 'attachment','is_active','is_paid','schedule_to_payroll','delete_status')
    list_filter=('approver','approved', 'category', 'application_date', 'attachment','is_active','is_paid','schedule_to_payroll','delete_status')
    list_display_links=["employee"]
    list_editable=  ('approver','approved', 'category', 'application_date', 'attachment','is_active','is_paid','schedule_to_payroll','delete_status')

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Get businesses owned by the user or related to the user's organization
        owner_businesses = Bussiness.objects.filter(
            Q(owner=request.user) | 
            Q(id=getattr(request.user, "organisation_id", None))
        )
        #print(owner_businesses)
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs
    
@admin.register(ClaimItems)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_per_page=10
    list_display = ('id', 'claim', 'expense_type', 'application_date', 'description', 'place_from', 'place_to', 'quantity_or_distance', 'unit_cost_or_rate', 'amount')
    search_fields= ('claim', 'expense_type', 'application_date', 'description', 'place_from', 'place_to', 'quantity_or_distance', 'unit_cost_or_rate', 'amount')
    list_filter = ('claim', 'expense_type', 'application_date', 'description', 'place_from', 'place_to', 'quantity_or_distance', 'unit_cost_or_rate', 'amount')
    
@admin.register(JobTitle)
class JobTitleAdmin(admin.ModelAdmin):
    list_display = ['title']
    search_fields = ['title']
    list_per_page = 10


@admin.register(JobGroup)
class JobGroupAdmin(admin.ModelAdmin):
    list_display = ['title', 'created_at', 'updated_at']
    search_fields = ['title', 'description']
    list_filter = ['created_at']
    list_per_page = 10


@admin.register(WorkersUnion)
class WorkersUnionAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'registration_number', 'contact_person', 'contact_email', 'created_at']
    search_fields = ['name', 'code', 'registration_number', 'contact_person']
    list_filter = ['created_at']
    list_per_page = 10


@admin.register(EmployeeBankAccount)
class EmployeeBankAccountAdmin(admin.ModelAdmin):
    list_display = ('employee', 'bank_institution', 'account_name', 'account_number', 'account_type', 'is_primary', 'status', 'is_verified')
    list_filter = ('bank_institution', 'account_type', 'is_primary', 'status', 'is_verified')
    search_fields = ('employee__user__first_name', 'employee__user__last_name', 'account_name', 'account_number', 'bank_institution__name')
    list_editable = ('is_primary', 'status', 'is_verified')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Employee Information', {
            'fields': ('employee',)
        }),
        ('Bank Details', {
            'fields': ('bank_institution', 'bank_branch', 'account_name', 'account_number', 'account_type')
        }),
        ('Additional Details', {
            'fields': ('opened_date',)
        }),
        ('Status', {
            'fields': ('is_primary', 'status', 'is_verified')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Get businesses owned by the current user
        owner_businesses = Bussiness.objects.filter(
            Q(id=getattr(request.user, "organisation_id", None))
        )
        # Filter the queryset based on business relationships
        qs = qs.filter(
            Q(employee__organisation__in=owner_businesses)
        ).distinct()
        return qs

