"""
Payroll Approval Service
Integrates with centralized approval system for payroll-specific workflows
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from approvals.models import ApprovalWorkflow, ApprovalStep, Approval, ApprovalRequest
from hrm.employees.models import Employee
from hrm.payroll.models import Payslip
from hrm.payroll_settings.services.utils import get_approval_thresholds, get_approver_by_role_and_department

logger = logging.getLogger('payroll')

User = get_user_model()


class PayrollApprovalService:
    """
    Service for managing payroll approval workflows using centralized approval system
    """
    
    def __init__(self):
        self.payroll_content_types = {
            'payslip': ContentType.objects.get_for_model(Payslip),
            # Note: CasualVoucher and ConsultantVoucher models will be added when they exist
        }
        # Initialize notification service lazily to avoid circular import
        self._notification_service = None
    
    @property
    def notification_service(self):
        """Lazy initialization of notification service to avoid circular import"""
        if self._notification_service is None:
            from .payroll_notification_service import PayrollNotificationService
            self._notification_service = PayrollNotificationService()
        return self._notification_service
    
    def create_payroll_approval_workflow(self, payroll_type, payroll_object, amount, department=None):
        """
        Create approval workflow for payroll items
        
        Args:
            payroll_type (str): Type of payroll ('payslip', 'casual_voucher', 'consultant_voucher')
            payroll_object: The payroll object (Payslip, CasualVoucher, or ConsultantVoucher)
            amount (Decimal): Total amount for approval
            department: Department for routing (optional)
        
        Returns:
            dict: Result with approval request details
        """
        try:
            with transaction.atomic():
                # Get or create payroll approval workflow
                workflow, created = self._get_or_create_payroll_workflow(payroll_type)
                
                if not workflow:
                    return {
                        'success': False,
                        'error': f'No approval workflow found for {payroll_type}'
                    }
                
                # Create approval request
                approval_request = ApprovalRequest.objects.create(
                    content_type=self.payroll_content_types[payroll_type],
                    object_id=payroll_object.id,
                    workflow=workflow,
                    requester=payroll_object.created_by or payroll_object.employee.user,
                    title=f"{payroll_type.replace('_', ' ').title()} Approval - {payroll_object.employee.user.get_full_name()}",
                    description=f"Approval required for {payroll_type} amounting to KES {amount:,.2f}",
                    amount=amount,
                    urgency=self._determine_urgency(amount),
                    status='submitted'
                )
                
                # Create approval steps based on amount thresholds and RBAC
                self._create_approval_steps(approval_request, amount, department)
                
                return {
                    'success': True,
                    'approval_request_id': approval_request.id,
                    'workflow_id': workflow.id,
                    'status': approval_request.status,
                    'message': f'Approval workflow created successfully for {payroll_type}'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Error creating approval workflow: {str(e)}'
            }
    
    def _get_or_create_payroll_workflow(self, payroll_type):
        """
        Get or create approval workflow for payroll type
        """
        workflow_name = f"Payroll {payroll_type.replace('_', ' ').title()} Approval"
        
        workflow, created = ApprovalWorkflow.objects.get_or_create(
            workflow_type='payroll',
            name=workflow_name,
            defaults={
                'description': f'Standard approval workflow for {payroll_type}',
                'requires_multiple_approvals': True,
                'approval_order_matters': True,
                'auto_approve_on_threshold': False,
                'is_active': True
            }
        )
        
        if created:
            # Create default approval steps
            self._create_default_approval_steps(workflow, payroll_type)
        
        return workflow
    
    def _create_default_approval_steps(self, workflow, payroll_type):
        """
        Create default approval steps for payroll workflow
        """
        steps_config = self._get_steps_config(payroll_type)
        
        for step_num, step_config in enumerate(steps_config, 1):
            ApprovalStep.objects.create(
                workflow=workflow,
                step_number=step_num,
                name=step_config['name'],
                approver_type=step_config['approver_type'],
                approver_role=step_config.get('approver_role'),
                approver_department=step_config.get('approver_department'),
                is_required=step_config.get('is_required', True),
                can_delegate=step_config.get('can_delegate', False),
                auto_approve=step_config.get('auto_approve', False)
            )
    
    def _get_steps_config(self, payroll_type):
        """
        Get approval steps configuration based on payroll type
        """
        base_steps = [
            {
                'name': 'Supervisor Review',
                'approver_type': 'role',
                'approver_role': 'supervisor',
                'is_required': True,
                'can_delegate': True
            },
            {
                'name': 'HR Manager Review',
                'approver_type': 'role',
                'approver_role': 'hr_manager',
                'is_required': True,
                'can_delegate': False
            }
        ]
        
        if payroll_type == 'payslip':
            # Regular payroll requires additional steps
            base_steps.extend([
                {
                    'name': 'Finance Review',
                    'approver_type': 'role',
                    'approver_role': 'finance_manager',
                    'is_required': True,
                    'can_delegate': False
                },
                {
                    'name': 'Director Approval',
                    'approver_type': 'role',
                    'approver_role': 'director',
                    'is_required': False,  # Only for high amounts
                    'can_delegate': False
                }
            ])
        elif payroll_type in ['casual_voucher', 'consultant_voucher']:
            # Casual/Consultant payments have simpler workflow
            base_steps.extend([
                {
                    'name': 'Finance Review',
                    'approver_type': 'role',
                    'approver_role': 'finance_manager',
                    'is_required': True,
                    'can_delegate': False
                }
            ])
        
        return base_steps
    
    def _create_approval_steps(self, approval_request, amount, department=None):
        """
        Create approval steps for the request based on amount thresholds
        """
        thresholds = get_approval_thresholds()
        workflow = approval_request.workflow
        
        # Get active steps for this workflow
        steps = workflow.steps.filter(is_active=True).order_by('step_number')
        
        for step in steps:
            # Check if step is required based on amount threshold
            if not self._is_step_required(step, amount, thresholds):
                continue
            
            # Get approver for this step
            approver = self._get_approver_for_step(step, department)
            
            if approver:
                approval = Approval.objects.create(
                    content_type=approval_request.content_type,
                    object_id=approval_request.object_id,
                    workflow=workflow,
                    step=step,
                    approver=approver,
                    approval_amount=amount,
                    status='pending'
                )
                
                # Send notification to approver
                try:
                    # Get the payroll object for notification
                    payroll_object = approval_request.content_type.get_object_for_this_type(id=approval_request.object_id)
                    self.notification_service.notify_approval_required(
                        approval=approval,
                        payroll_object=payroll_object,
                        amount=amount
                    )
                except Exception as e:
                    logger.error(f"Error sending approval notification: {str(e)}")
    
    def _is_step_required(self, step, amount, thresholds):
        """
        Check if approval step is required based on amount thresholds
        """
        # Director approval only for high amounts
        if step.approver_role == 'director':
            return amount >= thresholds.get('director_approval', Decimal('1000000'))
        
        # Finance approval for medium amounts
        if step.approver_role == 'finance_manager':
            return amount >= thresholds.get('finance_approval', Decimal('100000'))
        
        # Other steps are always required
        return True
    
    def _get_approver_for_step(self, step, department=None):
        """
        Get approver for a specific step based on role and department
        """
        if step.approver_type == 'user' and step.approver_user:
            return step.approver_user
        
        elif step.approver_type == 'role':
            return get_approver_by_role_and_department(
                step.approver_role, 
                department
            )
        
        elif step.approver_type == 'department_head' and department:
            # Get department head
            return get_approver_by_role_and_department('department_head', department)
        
        return None
    
    def _determine_urgency(self, amount):
        """
        Determine urgency based on amount
        """
        if amount >= Decimal('1000000'):
            return 'urgent'
        elif amount >= Decimal('500000'):
            return 'high'
        elif amount >= Decimal('100000'):
            return 'normal'
        else:
            return 'low'
    
    def get_pending_approvals(self, user):
        """
        Get pending approvals for a user
        """
        return Approval.objects.filter(
            approver=user,
            status='pending',
            content_type__in=self.payroll_content_types.values()
        ).select_related('workflow', 'step', 'content_type')
    
    def approve_payroll_item(self, approval_id, user, notes=None, comments=None):
        """
        Approve a payroll item
        """
        try:
            approval = Approval.objects.get(
                id=approval_id,
                approver=user,
                status='pending'
            )
            
            approval.approve(notes=notes, comments=comments)
            
            # Send notification about approval status change
            try:
                self.notification_service.notify_approval_status_change(
                    approval=approval,
                    status='approved',
                    notes=notes
                )
            except Exception as e:
                logger.error(f"Error sending approval status notification: {str(e)}")
            
            # Check if all approvals are complete
            request = ApprovalRequest.objects.get(
                content_type=approval.content_type,
                object_id=approval.object_id
            )
            
            if self._is_workflow_complete(request):
                request.approve()
                return {
                    'success': True,
                    'message': 'Payroll item approved and workflow completed',
                    'status': 'approved'
                }
            else:
                return {
                    'success': True,
                    'message': 'Approval recorded, waiting for other approvers',
                    'status': 'pending'
                }
                
        except Approval.DoesNotExist:
            return {
                'success': False,
                'error': 'Approval not found or already processed'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Error approving payroll item: {str(e)}'
            }
    
    def reject_payroll_item(self, approval_id, user, notes=None, comments=None):
        """
        Reject a payroll item
        """
        try:
            approval = Approval.objects.get(
                id=approval_id,
                approver=user,
                status='pending'
            )
            
            approval.reject(notes=notes, comments=comments)
            
            # Send notification about approval status change
            try:
                self.notification_service.notify_approval_status_change(
                    approval=approval,
                    status='rejected',
                    notes=notes
                )
            except Exception as e:
                logger.error(f"Error sending approval status notification: {str(e)}")
            
            # Mark the entire request as rejected
            request = ApprovalRequest.objects.get(
                content_type=approval.content_type,
                object_id=approval.object_id
            )
            request.reject()
            
            return {
                'success': True,
                'message': 'Payroll item rejected',
                'status': 'rejected'
            }
                
        except Approval.DoesNotExist:
            return {
                'success': False,
                'error': 'Approval not found or already processed'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Error rejecting payroll item: {str(e)}'
            }
    
    def _is_workflow_complete(self, request):
        """
        Check if all required approvals are complete
        """
        approvals = Approval.objects.filter(
            content_type=request.content_type,
            object_id=request.object_id
        )
        
        # Check if all required approvals are approved
        required_approvals = approvals.filter(step__is_required=True)
        approved_required = required_approvals.filter(status='approved')
        
        return required_approvals.count() == approved_required.count()
    
    def get_approval_summary(self, payroll_object):
        """
        Get approval summary for a payroll object
        """
        try:
            content_type = ContentType.objects.get_for_model(payroll_object)
            request = ApprovalRequest.objects.get(
                content_type=content_type,
                object_id=payroll_object.id
            )
            
            approvals = Approval.objects.filter(
                content_type=content_type,
                object_id=payroll_object.id
            ).select_related('step', 'approver')
            
            return {
                'success': True,
                'request_status': request.status,
                'approvals': [
                    {
                        'step_name': approval.step.name,
                        'approver': approval.approver.get_full_name() if approval.approver else 'Not Assigned',
                        'status': approval.status,
                        'notes': approval.notes,
                        'approved_at': approval.approved_at,
                        'rejected_at': approval.rejected_at
                    }
                    for approval in approvals
                ]
            }
            
        except ApprovalRequest.DoesNotExist:
            return {
                'success': False,
                'error': 'No approval request found for this payroll item'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Error getting approval summary: {str(e)}'
            }
