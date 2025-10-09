"""
Payroll Notification Service
Integrates with centralized notification system for payroll-specific notifications
"""

import logging
from datetime import datetime
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from notifications.services import NotificationService

logger = logging.getLogger('payroll')
User = get_user_model()


class PayrollNotificationService:
    """
    Service for sending payroll-related notifications using centralized notification system
    """
    
    def __init__(self):
        self.notification_service = NotificationService()
        # Initialize approval service lazily to avoid circular import
        self._approval_service = None
    
    @property
    def approval_service(self):
        """Lazy initialization of approval service to avoid circular import"""
        if self._approval_service is None:
            from .payroll_approval_service import PayrollApprovalService
            self._approval_service = PayrollApprovalService()
        return self._approval_service
    
    def notify_approval_required(self, approval, payroll_object, amount):
        """
        Notify approver that approval is required
        
        Args:
            approval: Approval object
            payroll_object: The payroll object (Payslip, etc.)
            amount: Amount requiring approval
        """
        try:
            if not approval.approver:
                logger.warning(f"No approver assigned for approval {approval.id}")
                return {'success': False, 'error': 'No approver assigned'}
            
            # Prepare notification data
            notification_data = {
                'approval_id': approval.id,
                'payroll_object_id': payroll_object.id,
                'payroll_object_type': payroll_object.__class__.__name__,
                'amount': str(amount),
                'step_name': approval.step.name,
                'workflow_name': approval.workflow.name,
                'employee_name': payroll_object.employee.user.get_full_name(),
                'employee_id': payroll_object.employee.id
            }
            
            # Determine urgency based on amount
            urgency = self._get_urgency_level(amount)
            
            # Create notification message
            title = f"Payroll Approval Required - {approval.step.name}"
            message = f"Approval required for {payroll_object.employee.user.get_full_name()}'s payroll amounting to KES {amount:,.2f}"
            
            # Send notification
            result = self.notification_service.send_notification(
                user=approval.approver,
                title=title,
                message=message,
                notification_type='payroll_approval_required',
                data=notification_data,
                email_subject=f"Payroll Approval Required - KES {amount:,.2f}",
                email_template='payroll/approval_required_email.html',
                action_url=f"/hrm/payroll/approvals/{approval.id}",
                send_email=True,
                send_push=True,
                send_in_app=True
            )
            
            logger.info(f"Approval notification sent to {approval.approver.email}: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error sending approval notification: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def notify_approval_status_change(self, approval, status, notes=None):
        """
        Notify relevant parties about approval status change
        
        Args:
            approval: Approval object
            status: New status ('approved', 'rejected')
            notes: Optional notes about the decision
        """
        try:
            # Get the payroll object
            payroll_object = approval.content_object
            if not payroll_object:
                logger.warning(f"No payroll object found for approval {approval.id}")
                return {'success': False, 'error': 'No payroll object found'}
            
            # Prepare notification data
            notification_data = {
                'approval_id': approval.id,
                'payroll_object_id': payroll_object.id,
                'payroll_object_type': payroll_object.__class__.__name__,
                'status': status,
                'step_name': approval.step.name,
                'approver_name': approval.approver.get_full_name() if approval.approver else 'System',
                'notes': notes or '',
                'employee_name': payroll_object.employee.user.get_full_name(),
                'employee_id': payroll_object.employee.id
            }
            
            # Determine who to notify based on status
            if status == 'approved':
                return self._notify_approval_approved(approval, payroll_object, notification_data)
            elif status == 'rejected':
                return self._notify_approval_rejected(approval, payroll_object, notification_data)
            
        except Exception as e:
            logger.error(f"Error sending approval status notification: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def _notify_approval_approved(self, approval, payroll_object, notification_data):
        """
        Notify about approval being approved
        """
        # Notify the employee
        employee_result = self.notification_service.send_notification(
            user=payroll_object.employee.user,
            title="Payroll Approved",
            message=f"Your payroll for {payroll_object.payroll_period} has been approved by {approval.approver.get_full_name()}",
            notification_type='payroll_approved',
            data=notification_data,
            email_subject="Payroll Approved",
            email_template='payroll/payroll_approved_email.html',
            action_url=f"/hrm/payroll/payslips/{payroll_object.id}",
            send_email=True,
            send_in_app=True
        )
        
        # Notify the requester (if different from employee)
        requester_result = None
        if approval.workflow.requests.first() and approval.workflow.requests.first().requester != payroll_object.employee.user:
            requester_result = self.notification_service.send_notification(
                user=approval.workflow.requests.first().requester,
                title="Payroll Approval Completed",
                message=f"Payroll approval for {payroll_object.employee.user.get_full_name()} has been completed",
                notification_type='payroll_approval_completed',
                data=notification_data,
                email_subject="Payroll Approval Completed",
                email_template='payroll/approval_completed_email.html',
                action_url=f"/hrm/payroll/approvals/{approval.id}",
                send_email=True,
                send_in_app=True
            )
        
        return {
            'success': True,
            'employee_notification': employee_result,
            'requester_notification': requester_result
        }
    
    def _notify_approval_rejected(self, approval, payroll_object, notification_data):
        """
        Notify about approval being rejected
        """
        # Notify the employee
        employee_result = self.notification_service.send_notification(
            user=payroll_object.employee.user,
            title="Payroll Rejected",
            message=f"Your payroll for {payroll_object.payroll_period} has been rejected by {approval.approver.get_full_name()}",
            notification_type='payroll_rejected',
            data=notification_data,
            email_subject="Payroll Rejected",
            email_template='payroll/payroll_rejected_email.html',
            action_url=f"/hrm/payroll/payslips/{payroll_object.id}",
            send_email=True,
            send_in_app=True
        )
        
        # Notify the requester
        requester_result = None
        if approval.workflow.requests.first():
            requester_result = self.notification_service.send_notification(
                user=approval.workflow.requests.first().requester,
                title="Payroll Approval Rejected",
                message=f"Payroll approval for {payroll_object.employee.user.get_full_name()} has been rejected",
                notification_type='payroll_approval_rejected',
                data=notification_data,
                email_subject="Payroll Approval Rejected",
                email_template='payroll/approval_rejected_email.html',
                action_url=f"/hrm/payroll/approvals/{approval.id}",
                send_email=True,
                send_in_app=True
            )
        
        return {
            'success': True,
            'employee_notification': employee_result,
            'requester_notification': requester_result
        }
    
    def notify_payslip_generated(self, payslip):
        """
        Notify employee that payslip has been generated
        
        Args:
            payslip: Payslip object
        """
        try:
            notification_data = {
                'payslip_id': payslip.id,
                'payroll_period': payslip.payroll_period.isoformat() if payslip.payroll_period else None,
                'gross_pay': str(payslip.gross_pay),
                'net_pay': str(payslip.net_pay),
                'employee_name': payslip.employee.user.get_full_name(),
                'employee_id': payslip.employee.id
            }
            
            result = self.notification_service.send_notification(
                user=payslip.employee.user,
                title="Payslip Generated",
                message=f"Your payslip for {payslip.payroll_period} has been generated. Net pay: KES {payslip.net_pay:,.2f}",
                notification_type='payslip_generated',
                data=notification_data,
                email_subject="Payslip Generated",
                email_template='payroll/payslip_generated_email.html',
                action_url=f"/hrm/payroll/payslips/{payslip.id}",
                send_email=True,
                send_in_app=True
            )
            
            logger.info(f"Payslip notification sent to {payslip.employee.user.email}: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error sending payslip notification: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def notify_payslip_emailed(self, payslip, email_status):
        """
        Notify about payslip email status
        
        Args:
            payslip: Payslip object
            email_status: Status of email sending ('sent', 'failed')
        """
        try:
            notification_data = {
                'payslip_id': payslip.id,
                'payroll_period': payslip.payroll_period.isoformat() if payslip.payroll_period else None,
                'email_status': email_status,
                'employee_name': payslip.employee.user.get_full_name(),
                'employee_id': payslip.employee.id
            }
            
            if email_status == 'sent':
                title = "Payslip Emailed Successfully"
                message = f"Payslip for {payslip.employee.user.get_full_name()} has been emailed successfully"
                notification_type = 'payslip_emailed_success'
                email_template = 'payroll/payslip_emailed_success_email.html'
            else:
                title = "Payslip Email Failed"
                message = f"Failed to email payslip for {payslip.employee.user.get_full_name()}"
                notification_type = 'payslip_emailed_failed'
                email_template = 'payroll/payslip_emailed_failed_email.html'
            
            # Notify HR/Admin about email status
            hr_users = self._get_hr_users()
            results = []
            
            for hr_user in hr_users:
                result = self.notification_service.send_notification(
                    user=hr_user,
                    title=title,
                    message=message,
                    notification_type=notification_type,
                    data=notification_data,
                    email_subject=title,
                    email_template=email_template,
                    action_url=f"/hrm/payroll/payslips/{payslip.id}",
                    send_email=True,
                    send_in_app=True
                )
                results.append({'user_id': hr_user.id, 'result': result})
            
            return {
                'success': True,
                'results': results
            }
            
        except Exception as e:
            logger.error(f"Error sending payslip email notification: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def notify_payroll_processing_complete(self, payroll_period, total_employees, total_amount):
        """
        Notify HR/Admin about payroll processing completion
        
        Args:
            payroll_period: Payroll period
            total_employees: Number of employees processed
            total_amount: Total payroll amount
        """
        try:
            notification_data = {
                'payroll_period': payroll_period.isoformat() if payroll_period else None,
                'total_employees': total_employees,
                'total_amount': str(total_amount),
                'processed_at': timezone.now().isoformat()
            }
            
            title = "Payroll Processing Complete"
            message = f"Payroll processing for {payroll_period} completed. {total_employees} employees, Total: KES {total_amount:,.2f}"
            
            # Notify HR/Admin users
            hr_users = self._get_hr_users()
            results = []
            
            for hr_user in hr_users:
                result = self.notification_service.send_notification(
                    user=hr_user,
                    title=title,
                    message=message,
                    notification_type='payroll_processing_complete',
                    data=notification_data,
                    email_subject=title,
                    email_template='payroll/payroll_processing_complete_email.html',
                    action_url="/hrm/payroll/",
                    send_email=True,
                    send_in_app=True
                )
                results.append({'user_id': hr_user.id, 'result': result})
            
            return {
                'success': True,
                'results': results
            }
            
        except Exception as e:
            logger.error(f"Error sending payroll processing notification: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def notify_approval_escalation(self, approval, escalation_reason):
        """
        Notify about approval escalation
        
        Args:
            approval: Approval object
            escalation_reason: Reason for escalation
        """
        try:
            notification_data = {
                'approval_id': approval.id,
                'escalation_reason': escalation_reason,
                'step_name': approval.step.name,
                'workflow_name': approval.workflow.name,
                'escalated_at': timezone.now().isoformat()
            }
            
            title = "Payroll Approval Escalated"
            message = f"Payroll approval has been escalated: {escalation_reason}"
            
            # Notify management
            management_users = self._get_management_users()
            results = []
            
            for user in management_users:
                result = self.notification_service.send_notification(
                    user=user,
                    title=title,
                    message=message,
                    notification_type='payroll_approval_escalated',
                    data=notification_data,
                    email_subject=title,
                    email_template='payroll/approval_escalated_email.html',
                    action_url=f"/hrm/payroll/approvals/{approval.id}",
                    send_email=True,
                    send_in_app=True
                )
                results.append({'user_id': user.id, 'result': result})
            
            return {
                'success': True,
                'results': results
            }
            
        except Exception as e:
            logger.error(f"Error sending escalation notification: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def _get_urgency_level(self, amount):
        """
        Determine urgency level based on amount
        """
        if amount >= Decimal('1000000'):
            return 'urgent'
        elif amount >= Decimal('500000'):
            return 'high'
        elif amount >= Decimal('100000'):
            return 'normal'
        else:
            return 'low'
    
    def _get_hr_users(self):
        """
        Get HR users for notifications
        """
        try:
            # Get users with HR-related roles
            hr_users = User.objects.filter(
                groups__name__in=['hr_manager', 'hr_staff', 'admin'],
                is_active=True
            ).distinct()
            
            if not hr_users.exists():
                # Fallback to superusers
                hr_users = User.objects.filter(is_superuser=True, is_active=True)
            
            return hr_users
            
        except Exception as e:
            logger.error(f"Error getting HR users: {str(e)}")
            return User.objects.none()
    
    def _get_management_users(self):
        """
        Get management users for notifications
        """
        try:
            # Get users with management roles
            management_users = User.objects.filter(
                groups__name__in=['director', 'manager', 'ceo', 'cfo'],
                is_active=True
            ).distinct()
            
            if not management_users.exists():
                # Fallback to HR users
                return self._get_hr_users()
            
            return management_users
            
        except Exception as e:
            logger.error(f"Error getting management users: {str(e)}")
            return User.objects.none()
    
    def send_bulk_payslip_notifications(self, payslips):
        """
        Send bulk notifications for multiple payslips
        
        Args:
            payslips: List of payslip objects
        """
        try:
            results = []
            
            for payslip in payslips:
                result = self.notify_payslip_generated(payslip)
                results.append({
                    'payslip_id': payslip.id,
                    'employee_name': payslip.employee.user.get_full_name(),
                    'result': result
                })
            
            return {
                'success': True,
                'total': len(payslips),
                'results': results
            }
            
        except Exception as e:
            logger.error(f"Error sending bulk payslip notifications: {str(e)}")
            return {'success': False, 'error': str(e)}
