from django.contrib import admin
from .models import ExpenseCategory, Expense, ExpensePayment, ExpenseEmailLog
from django.contrib.auth.admin import UserAdmin
from .models import *
from django.db.models import Q
from business.models import Branch

class BranchFilter(admin.SimpleListFilter):
    title = 'Branch'
    parameter_name = 'branch'

    def lookups(self, request, model_admin):
        if request.user.is_superuser:
            return Branch.objects.values_list('id', 'name')
        else:
            # Get the branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user).values_list('id', 'name')
            employee_branches = Branch.objects.filter(business__employees__user=request.user).values_list('id', 'name')
            # Combine the two sets of branches using union
            branches = owned_branches.union(employee_branches)
            # Convert queryset to list of tuples
            return list(branches)

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(branch__id=self.value())
        return queryset


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

class ExpensePaymentInline(admin.TabularInline):
    model = ExpensePayment
    extra = 1

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ('reference_no', 'branch', 'category', 'date_added', 'total_amount', 'expense_for_contact', 'is_refund', 'is_recurring')
    search_fields = ('reference_no', 'branch__name', 'category__name', 'expense_for_contact__user__username')
    list_filter = (BranchFilter,'branch', 'category', 'date_added', 'is_refund', 'is_recurring')
    inlines = [ExpensePaymentInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter expenses based on the obtained branches
            qs = qs.filter(branch__in=branches)
        return qs
    
@admin.register(ExpensePayment)
class ExpensePaymentAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ('expense', 'payment', 'amount', 'paid_on', 'payment_account')
    search_fields = ('expense__reference_no', 'payment__reference_number', 'payment__payment_method', 'payment_account__name')
    list_filter = ('paid_on', 'payment__payment_method')

@admin.register(ExpenseEmailLog)
class ExpenseEmailLogAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ('expense', 'email_type', 'recipient_email', 'status', 'sent_at', 'opened_at')
    list_filter = ('email_type', 'status', 'sent_at')
    search_fields = ('expense__reference_no', 'recipient_email')
    date_hierarchy = 'sent_at'
    readonly_fields = ('sent_at', 'opened_at', 'clicked_at')
