from django.contrib import admin
from .models import LeaveCategory, LeaveEntitlement, LeaveRequest, LeaveBalance

@admin.register(LeaveCategory)
class LeaveCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')

@admin.register(LeaveEntitlement)
class LeaveEntitlementAdmin(admin.ModelAdmin):
    list_display = ('employee', 'category', 'days_entitled', 'year')
    list_filter = ('year', 'category')
    search_fields = ('employee__first_name', 'employee__last_name', 'category__name')

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'category', 'start_date', 'end_date', 'status', 'approved_by')
    list_filter = ('status', 'category', 'start_date')
    search_fields = ('employee__first_name', 'employee__last_name', 'reason')
    readonly_fields = ('approved_at',)

@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'category', 'year', 'days_entitled', 'days_taken', 'days_remaining')
    list_filter = ('year', 'category')
    search_fields = ('employee__first_name', 'employee__last_name', 'category__name')
