from django.contrib import admin

from .models import *

# define inlines
# OrderApprovalInline removed - OrderApproval moved to centralized approvals app

# Register your models here.
admin.site.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    inlines = []
    list_display = ('id', 'order_number', 'order_date', 'vendor', 'status', 'notes', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at', 'updated_at')
    search_fields = ('vendor__name', 'order_number')
    readonly_fields = ('created_at', 'updated_at')
    list_display_links = ('id',)
    list_editable = ('status',)

# OrderApprovalAdmin removed - OrderApproval moved to centralized approvals app
    list_editable = ('status',)
