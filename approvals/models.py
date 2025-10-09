from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from core.models import Departments

User = get_user_model()


class ApprovalWorkflow(models.Model):
    """
    Centralized Approval Workflow - Standard ERP Approval System
    Defines approval workflows for different types of objects
    """
    WORKFLOW_TYPES = [
        ('purchase_order', 'Purchase Order'),
        ('expense', 'Expense'),
        ('invoice', 'Invoice'),
        ('leave_request', 'Leave Request'),
        ('overtime', 'Overtime'),
        ('payroll', 'Payroll'),
        ('contract', 'Contract'),
        ('requisition', 'Requisition'),
        ('general', 'General'),
    ]
    
    name = models.CharField(max_length=255, help_text="Name of the approval workflow")
    workflow_type = models.CharField(max_length=50, choices=WORKFLOW_TYPES, help_text="Type of workflow")
    description = models.TextField(blank=True, null=True)
    
    # Workflow settings
    requires_multiple_approvals = models.BooleanField(default=False, help_text="Whether multiple approvals are required")
    approval_order_matters = models.BooleanField(default=True, help_text="Whether approval order is important")
    auto_approve_on_threshold = models.BooleanField(default=False, help_text="Auto approve if amount is below threshold")
    approval_threshold = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, help_text="Amount threshold for auto approval")
    
    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'approval_workflows'
        ordering = ['name']
        indexes = [
            models.Index(fields=['workflow_type'], name='idx_approval_workflow_type'),
            models.Index(fields=['is_active'], name='idx_approval_workflow_active'),
        ]

    def __str__(self):
        return f"{self.name} ({self.workflow_type})"


class ApprovalStep(models.Model):
    """
    Individual steps in an approval workflow
    """
    workflow = models.ForeignKey(ApprovalWorkflow, on_delete=models.CASCADE, related_name='steps')
    step_number = models.PositiveIntegerField(help_text="Order of this step in the workflow")
    name = models.CharField(max_length=255, help_text="Name of this approval step")
    
    # Approver configuration
    approver_type = models.CharField(max_length=50, choices=[
        ('user', 'Specific User'),
        ('role', 'Role'),
        ('department_head', 'Department Head'),
        ('manager', 'Manager'),
        ('owner', 'Business Owner'),
    ], default='user')
    
    approver_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_steps')
    approver_role = models.CharField(max_length=100, blank=True, null=True, help_text="Role required for approval")
    approver_department = models.ForeignKey(Departments, on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_steps')
    
    # Step settings
    is_required = models.BooleanField(default=True, help_text="Whether this step is required")
    can_delegate = models.BooleanField(default=False, help_text="Whether approver can delegate to someone else")
    auto_approve = models.BooleanField(default=False, help_text="Whether this step auto-approves")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'approval_steps'
        ordering = ['workflow', 'step_number']
        unique_together = ['workflow', 'step_number']
        indexes = [
            models.Index(fields=['workflow'], name='idx_approval_step_workflow'),
            models.Index(fields=['step_number'], name='idx_approval_step_number'),
            models.Index(fields=['approver_type'], name='idx_approval_step_app_type'),
        ]

    def __str__(self):
        return f"{self.workflow.name} - Step {self.step_number}: {self.name}"


class Approval(models.Model):
    """
    Centralized Approval Model - Standard ERP Approval System
    Handles all approvals across the system using generic foreign keys
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('delegated', 'Delegated'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Generic content type for different object types
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Workflow and step
    workflow = models.ForeignKey(ApprovalWorkflow, on_delete=models.CASCADE, related_name='approvals')
    step = models.ForeignKey(ApprovalStep, on_delete=models.CASCADE, related_name='approvals')
    
    # Approver information
    approver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='approvals_given')
    delegated_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='delegated_approvals')
    
    # Approval details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, null=True)
    comments = models.TextField(blank=True, null=True, help_text="Internal comments")
    
    # Timestamps
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
    delegated_at = models.DateTimeField(blank=True, null=True)
    
    # Additional fields
    is_auto_approved = models.BooleanField(default=False, help_text="Whether this was auto-approved")
    approval_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, help_text="Amount being approved")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'approvals'
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id'], name='idx_approval_content'),
            models.Index(fields=['workflow'], name='idx_approval_workflow'),
            models.Index(fields=['step'], name='idx_approval_step'),
            models.Index(fields=['approver'], name='idx_approval_approver'),
            models.Index(fields=['status'], name='idx_approval_status'),
            models.Index(fields=['requested_at'], name='idx_approval_submitted_at'),
            models.Index(fields=['approved_at'], name='idx_approval_approved_at'),
        ]

    def __str__(self):
        return f"Approval for {self.content_object} by {self.approver} - {self.status}"

    def approve(self, notes=None, comments=None):
        """Approve this approval"""
        if self.status == 'pending':
            self.status = 'approved'
            self.approved_at = timezone.now()
            if notes:
                self.notes = notes
            if comments:
                self.comments = comments
            self.save()

    def reject(self, notes=None, comments=None):
        """Reject this approval"""
        if self.status == 'pending':
            self.status = 'rejected'
            self.rejected_at = timezone.now()
            if notes:
                self.notes = notes
            if comments:
                self.comments = comments
            self.save()

    def delegate(self, delegated_to, notes=None):
        """Delegate this approval to another user"""
        if self.status == 'pending' and self.step.can_delegate:
            self.status = 'delegated'
            self.delegated_to = delegated_to
            self.delegated_at = timezone.now()
            if notes:
                self.notes = notes
            self.save()

    @property
    def is_approved(self):
        """Check if approval is approved"""
        return self.status == 'approved'

    @property
    def is_rejected(self):
        """Check if approval is rejected"""
        return self.status == 'rejected'

    @property
    def is_pending(self):
        """Check if approval is pending"""
        return self.status == 'pending'

    @property
    def can_be_approved(self):
        """Check if approval can be approved"""
        return self.status == 'pending'

    @property
    def can_be_rejected(self):
        """Check if approval can be rejected"""
        return self.status == 'pending'


class ApprovalRequest(models.Model):
    """
    Approval Request - Initiates approval workflow for an object
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('in_progress', 'In Progress'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Generic content type for different object types
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Request details
    workflow = models.ForeignKey(ApprovalWorkflow, on_delete=models.CASCADE, related_name='requests')
    requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name='approval_requests')
    
    # Status and tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    current_step = models.ForeignKey(ApprovalStep, on_delete=models.SET_NULL, null=True, blank=True, related_name='current_requests')
    
    # Request details
    title = models.CharField(max_length=255, help_text="Title of the approval request")
    description = models.TextField(blank=True, null=True)
    urgency = models.CharField(max_length=20, choices=[
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ], default='normal')
    
    # Amount and financial details
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, help_text="Amount being requested")
    currency = models.CharField(max_length=3, default='KES')
    
    # Timestamps
    submitted_at = models.DateTimeField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'approval_requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id'], name='idx_approval_request_content'),
            models.Index(fields=['workflow'], name='idx_approval_request_workflow'),
            models.Index(fields=['requester'], name='idx_approval_request_requester'),
            models.Index(fields=['status'], name='idx_approval_request_status'),
            models.Index(fields=['urgency'], name='idx_approval_request_urgency'),
            models.Index(fields=['submitted_at'], name='idx_approval_request_submitted'),
        ]

    def __str__(self):
        return f"{self.title} - {self.status}"

    def submit(self):
        """Submit the approval request"""
        if self.status == 'draft':
            self.status = 'submitted'
            self.submitted_at = timezone.now()
            self.save()
            # Create first approval step
            self._create_approval_steps()

    def approve(self):
        """Approve the entire request"""
        if self.status == 'in_progress':
            self.status = 'approved'
            self.approved_at = timezone.now()
            self.save()

    def reject(self):
        """Reject the entire request"""
        if self.status in ['submitted', 'in_progress']:
            self.status = 'rejected'
            self.rejected_at = timezone.now()
            self.save()

    def cancel(self):
        """Cancel the request"""
        if self.status in ['draft', 'submitted']:
            self.status = 'cancelled'
            self.cancelled_at = timezone.now()
            self.save()

    def _create_approval_steps(self):
        """Create approval steps for this request"""
        steps = self.workflow.steps.filter(is_active=True).order_by('step_number')
        for step in steps:
            Approval.objects.create(
                content_type=self.content_type,
                object_id=self.object_id,
                workflow=self.workflow,
                step=step,
                approver=step.approver_user,
                approval_amount=self.amount
            )

    @property
    def is_approved(self):
        """Check if request is approved"""
        return self.status == 'approved'

    @property
    def is_rejected(self):
        """Check if request is rejected"""
        return self.status == 'rejected'

    @property
    def is_pending(self):
        """Check if request is pending"""
        return self.status in ['submitted', 'in_progress']

    @property
    def can_be_submitted(self):
        """Check if request can be submitted"""
        return self.status == 'draft'

    @property
    def can_be_cancelled(self):
        """Check if request can be cancelled"""
        return self.status in ['draft', 'submitted']
