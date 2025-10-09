from django.contrib import admin
from .models import Budget, BudgetLine


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('name',)


@admin.register(BudgetLine)
class BudgetLineAdmin(admin.ModelAdmin):
    list_display = ('budget', 'name', 'category', 'amount')
    list_filter = ('category',)
    search_fields = ('name',)
