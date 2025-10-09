"""
Core Celery tasks for the ERP system.
This module contains shared tasks that can be used across the ERP application.
Now uses centralized task management and caching systems.
"""
from celery import shared_task
import logging
from django.conf import settings

# Import centralized systems
from task_management.tasks import create_task, update_task_progress, complete_task, fail_task
from caching.cache_manager import cache_manager
from error_handling.handlers import handle_error

logger = logging.getLogger('ditapi_logger')

# Cache management tasks - now using centralized cache manager
@shared_task
def clear_cache(cache_key=None, module=None):
    """
    Task to clear a specific cache key or the entire cache using centralized cache manager
    """
    try:
        if cache_key:
            if module:
                cache_manager.clear_pattern(cache_key, module)
            else:
                cache_manager.delete(cache_key)
            logger.info(f"Cache key {cache_key} has been cleared")
        else:
            cache_manager.clear_all()
            logger.info("Entire cache has been cleared")
        return "Cache operation completed successfully"
    except Exception as e:
        handle_error(e, context={'module': 'core', 'function_name': 'clear_cache'})
        raise

# Email tasks - now using centralized notifications
@shared_task(bind=True)
def send_email_async(self, subject, body, recipient_list, attachments=None, user_id=None):
    """
    Task to send emails asynchronously using centralized notifications
    """
    from notifications.services import EmailService
    
    task_id = self.request.id
    task = None
    
    try:
        # Create task record
        task = create_task(
            task_id=task_id,
            task_type='email_distribution',
            title=f"Send email: {subject}",
            description=f"Sending email to {len(recipient_list)} recipients",
            module='core',
            user_id=user_id
        )
        
        # Mark as started
        task.mark_started()
        
        # Send email using centralized service
        email_service = EmailService()
        result = email_service.send_email(
            subject=subject,
            message=body,
            recipient_list=recipient_list,
            attachments=attachments,
            async_send=False  # Already running asynchronously
        )
        
        # Mark as completed
        task.mark_completed({'recipients': recipient_list, 'result': result})
        
        logger.info(f"Email sent to {recipient_list} with subject: {subject}")
        return result
        
    except Exception as e:
        if task:
            task.mark_failed(str(e))
        handle_error(e, context={
            'module': 'core', 
            'function_name': 'send_email_async',
            'subject': subject,
            'recipient_count': len(recipient_list)
        })
        raise

# Report generation tasks - now using centralized systems
@shared_task(bind=True)
def generate_report_async(self, report_type, params, user_id):
    """
    Task to generate reports asynchronously with centralized task management
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    task_id = self.request.id
    task = None
    
    try:
        user = User.objects.get(id=user_id)
        
        # Create task record
        task = create_task(
            task_id=task_id,
            task_type='report_generation',
            title=f"Generate {report_type} report",
            description=f"Generating {report_type} report for user {user.username}",
            module='core',
            user_id=user_id
        )
        
        # Mark as started
        task.mark_started()
        update_task_progress(task_id, progress=10, message="Starting report generation")
        
        # Store the report status in cache using centralized cache manager
        cache_key = f"report_status_{user_id}_{report_type}"
        cache_manager.set(cache_key, {"status": "processing", "progress": 10}, timeout=3600, module='core')
        
        update_task_progress(task_id, progress=30, message="Loading report data")
        
        # Implement report generation logic based on report_type
        result = None
        if report_type == "financial":
            from finance.accounts.reports import generate_financial_report
            result = generate_financial_report(params)
        elif report_type == "inventory":
            from ecommerce.stockinventory.reports import generate_inventory_report
            result = generate_inventory_report(params)
        elif report_type == "sales":
            from ecommerce.order.reports import generate_sales_report
            result = generate_sales_report(params)
        # Add other report types as needed
        
        update_task_progress(task_id, progress=80, message="Finalizing report")
        
        # Update the cache with completed status
        cache_manager.set(cache_key, {"status": "completed", "result": result}, timeout=3600, module='core')
        
        # Mark task as completed
        task.mark_completed({'report_type': report_type, 'result': result})
        
        # Notify user if needed
        send_email_async.delay(
            f"{report_type.capitalize()} Report Ready",
            f"Your requested report is now ready. Please log in to the system to view it.",
            [user.email],
            user_id=user_id
        )
        
        return {"status": "success", "report": result}
        
    except Exception as e:
        if task:
            task.mark_failed(str(e))
        
        # Update cache with error status
        cache_key = f"report_status_{user_id}_{report_type}"
        cache_manager.set(cache_key, {"status": "error", "error": str(e)}, timeout=3600, module='core')
        
        handle_error(e, context={
            'module': 'core', 
            'function_name': 'generate_report_async',
            'report_type': report_type,
            'user_id': user_id
        })
        raise
