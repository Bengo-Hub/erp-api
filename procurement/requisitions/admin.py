from django.contrib import admin

from .models import *

# define inlines
class RequisitionItemInline(admin.TabularInline):
    model = RequestItem
    extra = 0

# ApprovalInline removed - RequestApproval moved to centralized approvals app

@admin.register(ProcurementRequest)
class ProcurementRequestAdmin(admin.ModelAdmin):
    inlines = [RequisitionItemInline]
    list_display = ('id', 'request_type', 'purpose', 'requester', 'required_by_date', 'status', 'notes', 'created_at', 'updated_at')
    list_filter = ('request_type', 'status', 'created_at', 'updated_at')
    search_fields = ('requester__email', 'requester__first_name', 'requester__last_name', 'purpose')
    readonly_fields = ('created_at', 'updated_at')
    list_display_links = ('id',)
    list_editable = ('status',)
    list_per_page = 10

    def get_form(self, request, obj=None, **kwargs):
        """
        Returns a form for adding or editing a ProcurementRequest object.
        Sets the queryset for the requester field to only include users who are staff.
        """
        form = super(ProcurementRequestAdmin, self).get_form(request, obj, **kwargs)
        form.base_fields['requester'].queryset = User.objects.filter(is_staff=True)
        return form