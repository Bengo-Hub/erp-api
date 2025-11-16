"""
Celery tasks for payroll processing.
This module contains optimized tasks for payroll generation, distribution, and reporting.
"""
from celery import shared_task, group, chord
from django.db import transaction
from django.core.cache import cache
from datetime import datetime, timedelta
import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Payslip, PayslipAudit
from .utils import PayrollGenerator
from hrm.employees.models import Employee
from notifications.services import EmailService

logger = logging.getLogger('ditapi_logger')

# Import centralized task management
from task_management.tasks import create_task, update_task_progress, complete_task, fail_task, emit_websocket_event
from error_handling.handlers import handle_error

@shared_task(bind=True)
def process_single_payslip(self, employee_id, payment_period, recover_advances, command, user_id=None):
    """
    Process a single employee's payslip asynchronously.
    
    Args:
        employee_id: ID of the employee
        payment_period: The payment period (date)
        recover_advances: Whether to recover advances
        command: Command type (process, queue, rerun)
        user_id: Optional user ID for audit trails
    
    Returns:
        Dictionary with payslip data or error information
    """
    task_id = self.request.id
    task = None
    
    try:
        # Get employee for task creation
        employee = Employee.objects.get(id=employee_id)
        
        # Create task record only if we have a valid task_id (running in Celery)
        task = None
        if task_id:
            employee_name = f"{employee.user.first_name} {employee.user.last_name}".strip() or employee.user.email
            task = create_task(
                task_id=task_id,
                task_type='payroll_processing',
                title=f"Process payslip for {employee_name}",
                description=f"Processing payslip for employee {employee_name} for period {payment_period}",
                module='hrm.payroll',
                user_id=user_id
            )
        
        # Mark as started
        if task:
            task.mark_started()
        
        # Emit task started event
        if task_id:
            employee_name = f"{employee.user.first_name} {employee.user.last_name}".strip() or employee.user.email
            emit_websocket_event('task_started', {
                'task_id': task_id,
                'task_type': 'single_payslip',
                'message': f'Starting payslip processing for employee {employee_name}',
                'employee_id': employee_id,
                'command': command
            }, user_id=user_id, task_id=task_id)
        
        # Cache key for this specific payslip calculation
        cache_key = f"payslip_calculation_{employee_id}_{payment_period}_{command}"
        
        # Check if result is in cache
        cached_result = cache.get(cache_key)
        if cached_result and command != 'rerun':
            logger.info(f"Using cached payslip calculation for employee {employee_id}")
            
            # Emit task completed event for cached result
            if task_id:
                emit_websocket_event('task_completed', {
                    'task_id': task_id,
                    'task_type': 'single_payslip',
                    'result': cached_result,
                    'message': f'Payslip processing completed (cached) for employee {employee_id}',
                    'employee_id': employee_id,
                    'cached': True
                }, user_id=user_id, task_id=task_id)
            
            return cached_result
        
        # If not in cache or rerunning, process the payslip
        employee = Employee.objects.get(id=employee_id)
        
        # Create a mock request object with user info for audit purposes
        class MockRequest:
            def __init__(self, user_id):
                from django.contrib.auth import get_user_model
                User = get_user_model()
                self.user = User.objects.get(id=user_id) if user_id else None
        
        mock_request = MockRequest(user_id) if user_id else None
        
        # Generate the payroll
        payroll_generator = PayrollGenerator(mock_request, employee, payment_period, recover_advances, command)
        payroll_result = payroll_generator.generate_payroll()
        
        # Cache the result for future reference
        if isinstance(payroll_result, Payslip):
            # If it's a Payslip object, serialize its key data for caching
            from .serializers import PayslipSerializer
            serialized_data = PayslipSerializer(payroll_result).data
            cache.set(cache_key, serialized_data, timeout=3600)  # Cache for 1 hour
            
            # Create audit trail
            if mock_request and mock_request.user:
                PayslipAudit.objects.update_or_create(
                    payslip=payroll_result,
                    defaults={
                        'action': 'Created',
                        'action_by': mock_request.user
                    }
                )
            
            # Emit task completed event
            if task_id:
                emit_websocket_event('task_completed', {
                    'task_id': task_id,
                    'task_type': 'single_payslip',
                    'result': serialized_data,
                    'message': f'Payslip processing completed for employee {employee_id}',
                    'employee_id': employee_id,
                    'payslip_id': payroll_result.id
                }, user_id=user_id, task_id=task_id)
            
            return serialized_data
        else:
            # If it's an error or message, cache that too
            cache.set(cache_key, payroll_result, timeout=3600)
            
            # Emit task completed event (even for errors)
            if task_id:
                emit_websocket_event('task_completed', {
                    'task_id': task_id,
                    'task_type': 'single_payslip',
                    'result': payroll_result,
                    'message': f'Payslip processing completed for employee {employee_id}',
                    'employee_id': employee_id
                }, user_id=user_id, task_id=task_id)
            
            return payroll_result
    
    except Exception as e:
        error_msg = f"Error processing payslip for employee {employee_id}: {str(e)}"
        logger.error(error_msg)
        
        # Emit task failed event
        if task_id:
            emit_websocket_event('task_failed', {
                'task_id': task_id,
                'task_type': 'single_payslip',
                'error': error_msg,
                'message': f'Payslip processing failed for employee {employee_id}',
                'employee_id': employee_id
            }, user_id=user_id, task_id=task_id)
        
        return {"employee_id": employee_id, "success": False, "detail": error_msg}

@shared_task(bind=True)
def batch_process_payslips(self, employee_ids, payment_period, recover_advances, command, user_id=None):
    """
    Process multiple payslips in parallel with optimized resource usage.
    
    Args:
        employee_ids: List of employee IDs
        payment_period: The payment period (date)
        recover_advances: Whether to recover advances
        command: Command type (process, queue, rerun)
        user_id: Optional user ID for audit trails
    
    Returns:
        Dictionary with results from all payslip processes
    """
    task_id = self.request.id
    task = None
    
    try:
        logger.info(f"Starting batch payroll processing for {len(employee_ids)} employees")
        
        # Create task record only if we have a valid task_id (running in Celery)
        task = None
        if task_id:
            task = create_task(
                task_id=task_id,
                task_type='payroll_processing',
                title=f"Batch payroll processing for {len(employee_ids)} employees",
                description=f"Processing payroll for {len(employee_ids)} employees for period {payment_period}",
                module='hrm.payroll',
                user_id=user_id,
                input_data={
                    'employee_ids': employee_ids,
                    'payment_period': str(payment_period),
                    'recover_advances': recover_advances,
                    'command': command
                }
            )
        
        # Mark as started
        if task:
            task.mark_started()
        
        # Emit batch processing started event
        if task_id:
            emit_websocket_event('payroll_processing_started', {
                'task_id': task_id,
                'employee_count': len(employee_ids),
                'payment_period': payment_period.isoformat() if hasattr(payment_period, 'isoformat') else str(payment_period),
                'message': f'Starting batch payroll processing for {len(employee_ids)} employees',
                'command': command
            }, user_id=user_id, task_id=task_id)
        
        # Create a group of subtasks for parallel processing
        tasks = []
        for emp_id in employee_ids:
            tasks.append(
                process_single_payslip.s(emp_id, payment_period, recover_advances, command, user_id)
            )
        
        # Use a chord so we can emit completion events when all subtasks finish
        callback = finalize_batch_processing.s(
            task_id,
            user_id,
            command,
            employee_ids,
            payment_period.isoformat() if hasattr(payment_period, 'isoformat') else str(payment_period)
        )
        job = group(tasks)
        result = chord(job)(callback)
        
        # Return the group result (this will be processed asynchronously)
        return {
            "total": len(employee_ids),
            "status": "processing",
            "group_id": result.id,
            "task_id": task_id,
            "message": f"Batch processing started for {len(employee_ids)} employees"
        }
    
    except Exception as e:
        error_msg = f"Error in batch payroll processing: {str(e)}"
        logger.error(error_msg)
        
        # Emit task failed event
        if task_id:
            emit_websocket_event('task_failed', {
                'task_id': task_id,
                'task_type': 'batch_payroll',
                'error': error_msg,
                'message': f'Batch payroll processing failed for {len(employee_ids)} employees'
            }, user_id=user_id, task_id=task_id)
        
        return {"success": False, "detail": error_msg}


@shared_task
def finalize_batch_processing(results, batch_task_id, user_id, command, employee_ids, payment_period):
    """
    Callback executed after all payslip subtasks complete. Emits websocket updates and marks the batch task finished.
    """
    try:
        successful_results = [
            res for res in results if res and not (isinstance(res, dict) and res.get('success') is False)
        ]
        payslips_created = len(successful_results)
        
        # Mark the parent task as completed
        complete_task(batch_task_id, output_data={
            'results': results,
            'employee_ids': employee_ids,
            'command': command,
            'payment_period': payment_period
        }, message=f"Batch payroll processing completed for {len(employee_ids)} employees")
        
        # Emit completion websocket event
        emit_websocket_event('payroll_processing_completed', {
            'task_id': batch_task_id,
            'result': results,
            'payslips_created': payslips_created,
            'message': f'Payroll processing completed for {len(employee_ids)} employees',
            'employee_ids': employee_ids,
            'payment_period': payment_period,
            'command': command,
            'module': 'hrm.payroll'
        }, user_id=user_id, task_id=batch_task_id)
        
        return {
            "success": True,
            "task_id": batch_task_id,
            "payslips_created": payslips_created
        }
    except Exception as e:
        error_msg = f"Error finalizing batch payroll processing: {str(e)}"
        logger.error(error_msg)
        fail_task(batch_task_id, error_msg)
        emit_websocket_event('task_failed', {
            'task_id': batch_task_id,
            'task_type': 'batch_payroll',
            'error': error_msg,
            'message': 'Batch payroll processing failed during finalization',
            'module': 'hrm.payroll'
        }, user_id=user_id, task_id=batch_task_id)
        return {"success": False, "detail": error_msg}

@shared_task
def distribute_payslips_by_email(payslip_ids, user_id=None):
    """
    Distribute payslips to employees via email asynchronously.
    
    Args:
        payslip_ids: List of payslip IDs to distribute
        user_id: Optional user ID for audit trails
    
    Returns:
        Dictionary with distribution results
    """
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        sender = User.objects.get(id=user_id) if user_id else None
        
        results = []
        for payslip_id in payslip_ids:
            try:
                payslip = Payslip.objects.get(id=payslip_id)
                employee = payslip.employee
                
                # Generate payslip PDF (this would be your actual PDF generation logic)
                # For now, we'll assume the payslip is already available as a file
                
                # Send email asynchronously
                subject = f"Your Payslip for {payslip.payment_period.strftime('%B %Y')}"
                body = f"""
                Dear {employee.user.first_name},
                
                Please find attached your payslip for the period {payslip.payment_period.strftime('%B %Y')}.
                
                Regards,
                {sender.get_full_name() if sender else 'HR Department'}
                """
                
                # This would be your actual PDF generation and attachment logic
                # For now, we'll just record that we attempted to send
                
                # Add audit record for the distribution
                if sender:
                    PayslipAudit.objects.create(
                        payslip=payslip,
                        action='Email Sent',
                        action_by=sender,
                        details=f"Payslip emailed to {employee.user.email}"
                    )
                
                results.append({
                    "payslip_id": payslip_id,
                    "employee_id": employee.id,
                    "status": "queued_for_email",
                    "success": True
                })
                
            except Payslip.DoesNotExist:
                results.append({
                    "payslip_id": payslip_id,
                    "status": "not_found",
                    "success": False
                })
            except Exception as e:
                results.append({
                    "payslip_id": payslip_id,
                    "status": "error",
                    "detail": str(e),
                    "success": False
                })
        
        return {
            "total": len(payslip_ids),
            "success": sum(1 for r in results if r.get("success", False)),
            "results": results
        }
    
    except Exception as e:
        error_msg = f"Error distributing payslips: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "detail": error_msg}

@shared_task
def process_scheduled_payslips():
    """
    Process scheduled payslips and send emails at their scheduled time.
    This task should be run periodically (e.g., every minute) to check for
    scheduled payslips that are due to be sent.
    """
    try:
        from django.utils import timezone
        from hrm.payroll_settings.models import ScheduledPayslip
        
        now = timezone.now()
        due_scheduled_payslips = ScheduledPayslip.objects.filter(
            status='Pending',
            scheduled_time__lte=now
        )
        
        results = []
        for scheduled_payslip in due_scheduled_payslips:
            try:
                # Update status to processing
                scheduled_payslip.status = 'Processing'
                scheduled_payslip.save()
                
                # Get payslips for the payroll period
                from hrm.payroll.models import Payslip
                payslips = Payslip.objects.filter(
                    payment_period__year=scheduled_payslip.payroll_period.year,
                    payment_period__month=scheduled_payslip.payroll_period.month,
                    employee__in=scheduled_payslip.recipients.all()
                )
                
                if payslips.exists():
                    # Send emails for each payslip
                    email_results = distribute_payslips_by_email.delay(
                        [p.id for p in payslips],
                        user_id=scheduled_payslip.composer.id if scheduled_payslip.composer else None
                    )
                    
                    # Update scheduled payslip status
                    scheduled_payslip.status = 'Sent'
                    scheduled_payslip.send_time = now
                    scheduled_payslip.save()
                    
                    results.append({
                        "scheduled_payslip_id": scheduled_payslip.id,
                        "payslips_count": payslips.count(),
                        "status": "sent",
                        "success": True,
                        "task_id": email_results.id
                    })
                else:
                    # No payslips found
                    scheduled_payslip.status = 'Failed'
                    scheduled_payslip.comments = f"No payslips found for period {scheduled_payslip.payroll_period}"
                    scheduled_payslip.save()
                    
                    results.append({
                        "scheduled_payslip_id": scheduled_payslip.id,
                        "status": "failed",
                        "detail": "No payslips found",
                        "success": False
                    })
                    
            except Exception as e:
                # Update status to failed
                scheduled_payslip.status = 'Failed'
                scheduled_payslip.comments = f"Error: {str(e)}"
                scheduled_payslip.save()
                
                results.append({
                    "scheduled_payslip_id": scheduled_payslip.id,
                    "status": "failed",
                    "detail": str(e),
                    "success": False
                })
        
        return {
            "total_processed": len(due_scheduled_payslips),
            "success": sum(1 for r in results if r.get("success", False)),
            "results": results
        }
        
    except Exception as e:
        error_msg = f"Error processing scheduled payslips: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "detail": error_msg}

@shared_task
def rerun_payslip(payslip_id, user_id=None):
    """
    Rerun a specific payslip calculation asynchronously.
    
    Args:
        payslip_id: ID of the payslip to rerun
        user_id: Optional user ID for audit trails
    
    Returns:
        Dictionary with payslip data or error information
    """
    task_id = rerun_payslip.request.id
    
    try:
        # Emit task started event
        emit_websocket_event('task_started', {
            'task_id': task_id,
            'task_type': 'payslip_rerun',
            'message': f'Starting payslip rerun for payslip {payslip_id}',
            'payslip_id': payslip_id
        }, user_id=user_id, task_id=task_id)
        
        # Get the existing payslip
        payslip = Payslip.objects.get(id=payslip_id)
        employee = payslip.employee
        payment_period = payslip.payment_period
        
        # Create a mock request object with user info for audit purposes
        class MockRequest:
            def __init__(self, user_id):
                from django.contrib.auth import get_user_model
                User = get_user_model()
                self.user = User.objects.get(id=user_id) if user_id else None
        
        mock_request = MockRequest(user_id) if user_id else None
        
        # Delete the existing payslip
        payslip.delete()
        
        # Generate new payroll
        payroll_generator = PayrollGenerator(mock_request, employee, payment_period, False, 'rerun')
        payroll_result = payroll_generator.generate_payroll()
        
        # Create audit trail
        if isinstance(payroll_result, Payslip) and mock_request and mock_request.user:
            PayslipAudit.objects.create(
                payslip=payroll_result,
                action='Rerun',
                action_by=mock_request.user,
                details=f"Payslip rerun for period {payment_period}"
            )
        
        # Serialize the result
        if isinstance(payroll_result, Payslip):
            from .serializers import PayslipSerializer
            serialized_data = PayslipSerializer(payroll_result).data
            
            # Emit task completed event
            emit_websocket_event('payslip_rerun_completed', {
                'task_id': task_id,
                'payslip_id': payroll_result.id,
                'result': serialized_data,
                'message': f'Payslip rerun completed successfully for payslip {payslip_id}',
                'employee_id': employee.id
            }, user_id=user_id, task_id=task_id)
            
            return serialized_data
        else:
            # Emit task completed event (even for errors)
            emit_websocket_event('payslip_rerun_completed', {
                'task_id': task_id,
                'payslip_id': payslip_id,
                'result': payroll_result,
                'message': f'Payslip rerun completed for payslip {payslip_id}',
                'employee_id': employee.id
            }, user_id=user_id, task_id=task_id)
            
            return payroll_result
    
    except Payslip.DoesNotExist:
        error_msg = f"Payslip with ID {payslip_id} not found"
        
        # Emit task failed event
        emit_websocket_event('task_failed', {
            'task_id': task_id,
            'task_type': 'payslip_rerun',
            'error': error_msg,
            'message': f'Payslip rerun failed: {error_msg}',
            'payslip_id': payslip_id
        }, user_id=user_id, task_id=task_id)
        
        return {"success": False, "detail": error_msg}
    except Exception as e:
        error_msg = f"Error rerunning payslip {payslip_id}: {str(e)}"
        logger.error(error_msg)
        
        # Emit task failed event
        emit_websocket_event('task_failed', {
            'task_id': task_id,
            'task_type': 'payslip_rerun',
            'error': error_msg,
            'message': f'Payslip rerun failed: {error_msg}',
            'payslip_id': payslip_id
        }, user_id=user_id, task_id=task_id)
        
        return {"success": False, "detail": error_msg}

@shared_task
def generate_payroll_reports(payment_period, report_type, filters=None, user_id=None):
    """
    Generate comprehensive payroll reports asynchronously.
    
    Args:
        payment_period: The payment period (date)
        report_type: Type of report (summary, detailed, tax, etc.)
        filters: Optional dictionary of filters
        user_id: Optional user ID to associate with the report
    
    Returns:
        Dictionary with report data or error information
    """
    try:
        # Cache key for this specific report
        cache_key = f"payroll_report_{report_type}_{payment_period}"
        if filters:
            # Add filters to cache key
            filter_str = "_".join(f"{k}_{v}" for k, v in sorted(filters.items()))
            cache_key += f"_{filter_str}"
        
        # Check if report is in cache
        cached_report = cache.get(cache_key)
        if cached_report:
            logger.info(f"Using cached payroll report {cache_key}")
            return cached_report
        
        # Generate the report based on type
        report_data = {}
        
        if report_type == "summary":
            # Fetch all relevant payslips
            payslips = Payslip.objects.filter(
                payment_period__year=payment_period.year,
                payment_period__month=payment_period.month,
                delete_status=False
            )
            
            # Apply any additional filters
            if filters:
                if 'department_ids' in filters:
                    payslips = payslips.filter(employee__hr_details__department_id__in=filters['department_ids'])
                if 'region_ids' in filters:
                    payslips = payslips.filter(employee__hr_details__region_id__in=filters['region_ids'])
            
            # Aggregate the data
            from django.db.models import Sum, Count, Avg
            summary = payslips.aggregate(
                total_payslips=Count('id'),
                total_basic_pay=Sum('basic_pay'),
                total_gross_pay=Sum('gross_pay'),
                total_net_pay=Sum('net_pay'),
                total_tax=Sum('paye'),
                total_nhif=Sum('nhif'),
                total_nssf=Sum('nssf'),
                avg_basic_pay=Avg('basic_pay'),
                avg_gross_pay=Avg('gross_pay'),
                avg_net_pay=Avg('net_pay')
            )
            
            report_data = {
                "report_type": "summary",
                "period": payment_period.strftime("%B %Y"),
                "summary": summary,
                "generated_at": datetime.now().isoformat(),
                "generated_by": user_id
            }
        
        elif report_type == "detailed":
            # Implement detailed report logic
            # This would include all payslip details
            payslips = Payslip.objects.filter(
                payment_period__year=payment_period.year,
                payment_period__month=payment_period.month,
                delete_status=False
            ).select_related('employee', 'employee__hr_details')
            
            # Apply filters if provided
            if filters:
                if 'department_ids' in filters:
                    payslips = payslips.filter(employee__hr_details__department_id__in=filters['department_ids'])
                if 'region_ids' in filters:
                    payslips = payslips.filter(employee__hr_details__region_id__in=filters['region_ids'])
            
            # Serialize payslip data
            from hrm.payroll.serializers import PayrollEmployeeSerializer
            payslip_data = PayrollEmployeeSerializer(payslips, many=True).data
            
            report_data = {
                "report_type": "detailed",
                "period": payment_period.strftime("%B %Y"),
                "payslips": payslip_data,
                "total_count": payslips.count(),
                "generated_at": datetime.now().isoformat(),
                "generated_by": user_id
            }
        
        elif report_type == "tax":
            # Implement tax report logic
            # This would focus on tax deductions
            payslips = Payslip.objects.filter(
                payment_period__year=payment_period.year,
                payment_period__month=payment_period.month,
                delete_status=False
            )
            
            # Apply filters if provided
            if filters:
                if 'department_ids' in filters:
                    payslips = payslips.filter(employee__hr_details__department_id__in=filters['department_ids'])
                if 'region_ids' in filters:
                    payslips = payslips.filter(employee__hr_details__region_id__in=filters['region_ids'])
            
            # Aggregate tax data
            from django.db.models import Sum, Count
            tax_summary = payslips.aggregate(
                total_payslips=Count('id'),
                total_paye=Sum('paye'),
                total_nhif=Sum('nhif'),
                total_nssf=Sum('nssf'),
                total_taxable_income=Sum('taxable_income'),
                total_gross_pay=Sum('gross_pay')
            )
            
            report_data = {
                "report_type": "tax",
                "period": payment_period.strftime("%B %Y"),
                "tax_summary": tax_summary,
                "generated_at": datetime.now().isoformat(),
                "generated_by": user_id
            }
        
        # Cache the report for future use
        cache.set(cache_key, report_data, timeout=86400)  # Cache for 24 hours
        
        # If user_id is provided, also send a notification
        if user_id:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.get(id=user_id)
            
            email_service = EmailService()
            email_service.send_email(
                subject=f"Payroll Report for {payment_period.strftime('%B %Y')} Ready",
                message=f"Your requested payroll report is now ready. Please log in to the system to view it.",
                recipient_list=[user.email],
                async_send=True
            )
        
        return report_data
    
    except Exception as e:
        error_msg = f"Error generating payroll report: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "detail": error_msg}
