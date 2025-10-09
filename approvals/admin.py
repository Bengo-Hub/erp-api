from django.contrib import admin
from .models import ApprovalWorkflow, ApprovalStep, Approval, ApprovalRequest


class ApprovalStepInline(admin.TabularInline):
    model = ApprovalStep
    extra = 1
    fields = ['step_number', 'name', 'approver_type', 'approver_user', 'approver_role', 'approver_department', 'is_required', 'can_delegate', 'auto_approve']


@admin.register(ApprovalWorkflow)
class ApprovalWorkflowAdmin(admin.ModelAdmin):
    list_display = ['name', 'workflow_type', 'requires_multiple_approvals', 'approval_order_matters', 'is_active']
    list_filter = ['workflow_type', 'requires_multiple_approvals', 'approval_order_matters', 'auto_approve_on_threshold', 'is_active']
    search_fields = ['name', 'description']
    inlines = [ApprovalStepInline]
    
    fieldsets = (
        ('Workflow Information', {
            'fields': ['name', 'workflow_type', 'description']
        }),
        ('Workflow Settings', {
            'fields': ['requires_multiple_approvals', 'approval_order_matters', 'auto_approve_on_threshold', 'approval_threshold']
        }),
        ('Status', {
            'fields': ['is_active']
        }),
    )


@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    list_display = ['workflow', 'step_number', 'name', 'approver_type', 'is_required', 'auto_approve']
    list_filter = ['workflow', 'approver_type', 'is_required', 'can_delegate', 'auto_approve']
    search_fields = ['workflow__name', 'name', 'approver_role']
    ordering = ['workflow', 'step_number']


@admin.register(Approval)
class ApprovalAdmin(admin.ModelAdmin):
    list_display = ['content_object', 'workflow', 'step', 'approver', 'status', 'requested_at']
    list_filter = ['workflow', 'step', 'status', 'requested_at', 'approved_at', 'rejected_at']
    search_fields = ['content_object__id', 'approver__username', 'notes', 'comments']
    readonly_fields = ['requested_at', 'approved_at', 'rejected_at', 'delegated_at']
    
    fieldsets = (
        ('Approval Information', {
            'fields': ['content_type', 'object_id', 'workflow', 'step']
        }),
        ('Approver Information', {
            'fields': ['approver', 'delegated_to']
        }),
        ('Status & Details', {
            'fields': ['status', 'notes', 'comments', 'is_auto_approved', 'approval_amount']
        }),
        ('Timestamps', {
            'fields': ['requested_at', 'approved_at', 'rejected_at', 'delegated_at']
        }),
    )

    actions = ['approve_selected', 'reject_selected']

    def approve_selected(self, request, queryset):
        updated = 0
        for approval in queryset.filter(status='pending'):
            approval.approve()
            updated += 1
        self.message_user(request, f'{updated} approvals processed.')
    approve_selected.short_description = 'Approve selected approvals'

    def reject_selected(self, request, queryset):
        updated = 0
        for approval in queryset.filter(status='pending'):
            approval.reject()
            updated += 1
        self.message_user(request, f'{updated} approvals rejected.')
    reject_selected.short_description = 'Reject selected approvals'


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ['title', 'workflow', 'requester', 'status', 'urgency', 'amount', 'submitted_at']
    list_filter = ['workflow', 'status', 'urgency', 'submitted_at', 'approved_at', 'rejected_at']
    search_fields = ['title', 'description', 'requester__username']
    readonly_fields = ['submitted_at', 'approved_at', 'rejected_at', 'cancelled_at']
    
    fieldsets = (
        ('Request Information', {
            'fields': ['content_type', 'object_id', 'workflow', 'current_step', 'title', 'description', 'urgency']
        }),
        ('Requester & Amount', {
            'fields': ['requester', 'amount', 'currency']
        }),
        ('Status & Notes', {
            'fields': ['status', 'notes']
        }),
        ('Timestamps', {
            'fields': ['submitted_at', 'approved_at', 'rejected_at', 'cancelled_at']
        }),
    )

    actions = ['submit_requests', 'approve_requests', 'reject_requests', 'cancel_requests']

    def submit_requests(self, request, queryset):
        updated = 0
        for req in queryset.filter(status='draft'):
            req.submit()
            updated += 1
        self.message_user(request, f'{updated} requests submitted.')
    submit_requests.short_description = 'Submit selected requests'

    def approve_requests(self, request, queryset):
        updated = 0
        for req in queryset.filter(status='in_progress'):
            req.approve()
            updated += 1
        self.message_user(request, f'{updated} requests approved.')
    approve_requests.short_description = 'Approve selected requests'

    def reject_requests(self, request, queryset):
        updated = 0
        for req in queryset.filter(status__in=['submitted', 'in_progress']):
            req.reject()
            updated += 1
        self.message_user(request, f'{updated} requests rejected.')
    reject_requests.short_description = 'Reject selected requests'

    def cancel_requests(self, request, queryset):
        updated = 0
        for req in queryset.filter(status__in=['draft', 'submitted']):
            req.cancel()
            updated += 1
        self.message_user(request, f'{updated} requests cancelled.')
    cancel_requests.short_description = 'Cancel selected requests'
