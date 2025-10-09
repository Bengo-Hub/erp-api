"""
Centralized task management for all ERP modules
"""
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from .models import Task, TaskLog, TaskStatus, TaskType, TaskPriority

User = get_user_model()

logger = logging.getLogger('ditapi_logger')


def emit_websocket_event(event_type: str, data: Dict[str, Any], user_id: Optional[int] = None, task_id: Optional[str] = None):
    """
    Emit WebSocket event to notify frontend of task status changes
    Centralized for all ERP modules
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return

        # Add timestamp to all events
        data['timestamp'] = datetime.now().isoformat()

        # Send to general task updates group
        async_to_sync(channel_layer.group_send)(
            'task_updates',
            {
                'type': event_type,
                **data
            }
        )

        # Send to user-specific group if user_id provided
        if user_id:
            async_to_sync(channel_layer.group_send)(
                f'task_user_{user_id}',
                {
                    'type': event_type,
                    **data
                }
            )

        # Send to task-specific group if task_id provided
        if task_id:
            async_to_sync(channel_layer.group_send)(
                f'task_{task_id}',
                {
                    'type': event_type,
                    **data
                }
            )

        # Send to module-specific group
        if 'module' in data:
            async_to_sync(channel_layer.group_send)(
                f'task_module_{data["module"]}',
                {
                    'type': event_type,
                    **data
                }
            )

    except Exception as e:
        logger.error(f"Error emitting WebSocket event {event_type}: {e}")


def create_task(task_id: str, task_type: str, title: str, description: str = "", 
                module: str = "core", user_id: int = None, priority: str = TaskPriority.NORMAL,
                input_data: Dict = None, metadata: Dict = None) -> Task:
    """
    Create a new task record
    """
    try:
        user = User.objects.get(id=user_id) if user_id else None
        
        task = Task.objects.create(
            task_id=task_id,
            task_type=task_type,
            title=title,
            description=description,
            module=module,
            created_by=user,
            priority=priority,
            input_data=input_data or {},
            metadata=metadata or {}
        )
        
        # Log task creation
        TaskLog.objects.create(
            task=task,
            level='info',
            message=f"Task created: {title}",
            data={'task_type': task_type, 'module': module}
        )
        
        # Emit WebSocket event
        emit_websocket_event('task_created', {
            'task_id': task_id,
            'task_type': task_type,
            'title': title,
            'module': module,
            'status': task.status,
            'message': f'Task "{title}" has been created'
        }, user_id=user_id, task_id=task_id)
        
        return task
        
    except Exception as e:
        logger.error(f"Error creating task {task_id}: {e}")
        raise


def update_task_progress(task_id: str, progress: int = None, processed_items: int = None, 
                        total_items: int = None, message: str = None):
    """
    Update task progress
    """
    try:
        task = Task.objects.get(task_id=task_id)
        
        if progress is not None:
            task.progress = min(100, max(0, progress))
        
        if processed_items is not None:
            task.processed_items = processed_items
        
        if total_items is not None:
            task.total_items = total_items
        
        task.save(update_fields=['progress', 'processed_items', 'total_items'])
        
        # Log progress update
        if message:
            TaskLog.objects.create(
                task=task,
                level='info',
                message=message,
                data={'progress': task.progress, 'processed_items': task.processed_items}
            )
        
        # Emit WebSocket event
        emit_websocket_event('task_progress', {
            'task_id': task_id,
            'progress': task.progress,
            'processed_items': task.processed_items,
            'total_items': task.total_items,
            'message': message or f'Progress: {task.progress}%'
        }, user_id=task.created_by.id if task.created_by else None, task_id=task_id)
        
    except Task.DoesNotExist:
        logger.error(f"Task {task_id} not found for progress update")
    except Exception as e:
        logger.error(f"Error updating task progress {task_id}: {e}")


def complete_task(task_id: str, output_data: Dict = None, message: str = None):
    """
    Mark task as completed
    """
    try:
        task = Task.objects.get(task_id=task_id)
        task.mark_completed(output_data)
        
        # Log completion
        TaskLog.objects.create(
            task=task,
            level='info',
            message=message or f"Task completed successfully",
            data={'output_data': output_data}
        )
        
        # Emit WebSocket event
        emit_websocket_event('task_completed', {
            'task_id': task_id,
            'task_type': task.task_type,
            'title': task.title,
            'module': task.module,
            'status': task.status,
            'duration': str(task.duration) if task.duration else None,
            'message': message or f'Task "{task.title}" completed successfully'
        }, user_id=task.created_by.id if task.created_by else None, task_id=task_id)
        
    except Task.DoesNotExist:
        logger.error(f"Task {task_id} not found for completion")
    except Exception as e:
        logger.error(f"Error completing task {task_id}: {e}")


def fail_task(task_id: str, error_message: str, error_traceback: str = None):
    """
    Mark task as failed
    """
    try:
        task = Task.objects.get(task_id=task_id)
        task.mark_failed(error_message, error_traceback)
        
        # Log failure
        TaskLog.objects.create(
            task=task,
            level='error',
            message=f"Task failed: {error_message}",
            data={'error_traceback': error_traceback}
        )
        
        # Emit WebSocket event
        emit_websocket_event('task_failed', {
            'task_id': task_id,
            'task_type': task.task_type,
            'title': task.title,
            'module': task.module,
            'status': task.status,
            'error_message': error_message,
            'message': f'Task "{task.title}" failed: {error_message}'
        }, user_id=task.created_by.id if task.created_by else None, task_id=task_id)
        
    except Task.DoesNotExist:
        logger.error(f"Task {task_id} not found for failure")
    except Exception as e:
        logger.error(f"Error failing task {task_id}: {e}")


@shared_task(bind=True)
def generic_task_wrapper(self, task_id: str, task_type: str, title: str, 
                        description: str, module: str, user_id: int,
                        function_name: str, *args, **kwargs):
    """
    Generic task wrapper for any ERP module function
    """
    try:
        # Create task record
        task = create_task(
            task_id=self.request.id,
            task_type=task_type,
            title=title,
            description=description,
            module=module,
            user_id=user_id
        )
        
        # Mark as started
        task.mark_started()
        emit_websocket_event('task_started', {
            'task_id': task_id,
            'task_type': task_type,
            'title': title,
            'module': module,
            'status': task.status,
            'message': f'Task "{title}" started'
        }, user_id=user_id, task_id=task_id)
        
        # Import and execute the function
        module_parts = module.split('.')
        if len(module_parts) >= 2:
            app_name = module_parts[0]
            module_name = '.'.join(module_parts[1:])
            
            # Dynamic import
            import importlib
            module_obj = importlib.import_module(f'{app_name}.{module_name}')
            function = getattr(module_obj, function_name)
            
            # Execute function with progress callback
            def progress_callback(progress, message=None):
                update_task_progress(task_id, progress=progress, message=message)
            
            result = function(progress_callback=progress_callback, *args, **kwargs)
            
            # Mark as completed
            complete_task(task_id, output_data={'result': result})
            return result
            
        else:
            raise ValueError(f"Invalid module format: {module}")
            
    except Exception as e:
        error_message = str(e)
        error_traceback = str(e.__traceback__) if hasattr(e, '__traceback__') else None
        fail_task(task_id, error_message, error_traceback)
        raise


@shared_task
def cleanup_old_tasks(days_old: int = 30):
    """
    Cleanup old completed/failed tasks
    """
    try:
        from datetime import timedelta
        cutoff_date = timezone.now() - timedelta(days=days_old)
        
        old_tasks = Task.objects.filter(
            status__in=[TaskStatus.COMPLETED, TaskStatus.FAILED],
            completed_at__lt=cutoff_date
        )
        
        count = old_tasks.count()
        old_tasks.delete()
        
        logger.info(f"Cleaned up {count} old tasks")
        return f"Cleaned up {count} old tasks"
        
    except Exception as e:
        logger.error(f"Error cleaning up old tasks: {e}")
        raise


@shared_task
def generate_task_report(module: str = None, task_type: str = None, 
                        start_date: datetime = None, end_date: datetime = None):
    """
    Generate task performance report
    """
    try:
        tasks = Task.objects.all()
        
        if module:
            tasks = tasks.filter(module=module)
        if task_type:
            tasks = tasks.filter(task_type=task_type)
        if start_date:
            tasks = tasks.filter(created_at__gte=start_date)
        if end_date:
            tasks = tasks.filter(created_at__lte=end_date)
        
        # Calculate statistics
        total_tasks = tasks.count()
        completed_tasks = tasks.filter(status=TaskStatus.COMPLETED).count()
        failed_tasks = tasks.filter(status=TaskStatus.FAILED).count()
        running_tasks = tasks.filter(status=TaskStatus.RUNNING).count()
        
        # Calculate average duration
        completed_with_duration = tasks.filter(
            status=TaskStatus.COMPLETED,
            started_at__isnull=False,
            completed_at__isnull=False
        )
        
        total_duration = sum(
            (task.completed_at - task.started_at).total_seconds() 
            for task in completed_with_duration
        )
        avg_duration = total_duration / completed_with_duration.count() if completed_with_duration.count() > 0 else 0
        
        report = {
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'failed_tasks': failed_tasks,
            'running_tasks': running_tasks,
            'success_rate': (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
            'average_duration_seconds': avg_duration,
            'module': module,
            'task_type': task_type,
            'start_date': start_date.isoformat() if start_date else None,
            'end_date': end_date.isoformat() if end_date else None,
        }
        
        return report
        
    except Exception as e:
        logger.error(f"Error generating task report: {e}")
        raise