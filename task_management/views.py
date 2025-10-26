"""
Centralized task management views for all ERP modules
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.utils import timezone
from django.db.models import Q, Count, Avg
from datetime import timedelta
from jsonschema import validate as jsonschema_validate, ValidationError
import json

from .models import Task, TaskLog, TaskTemplate
from .serializers import TaskSerializer, TaskLogSerializer, TaskTemplateSerializer
from .filters import TaskFilter
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class TaskViewSet(BaseModelViewSet):
    """
    Centralized task management for all ERP modules
    """
    queryset = Task.objects.all().select_related('created_by', 'assigned_to')
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = TaskFilter
    search_fields = ['title', 'description', 'module', 'task_type']
    ordering_fields = ['created_at', 'started_at', 'completed_at', 'priority', 'status']
    ordering = ['-created_at']

    def get_queryset(self):
        """Filter tasks based on user permissions"""
        queryset = super().get_queryset()
        
        # If user is not staff, only show their own tasks
        if not self.request.user.is_staff:
            queryset = queryset.filter(created_by=self.request.user)
        
        return queryset

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Get task dashboard statistics"""
        try:
            correlation_id = get_correlation_id(request)
            # Get date range from query params
            days = int(request.query_params.get('days', 7))
            start_date = timezone.now() - timedelta(days=days)
            
            # Filter tasks by date range
            tasks = self.get_queryset().filter(created_at__gte=start_date)
            
            # Calculate statistics
            stats = {
                'total_tasks': tasks.count(),
                'completed_tasks': tasks.filter(status='completed').count(),
                'failed_tasks': tasks.filter(status='failed').count(),
                'running_tasks': tasks.filter(status='running').count(),
                'pending_tasks': tasks.filter(status='pending').count(),
                'success_rate': 0,
                'average_duration': 0,
                'tasks_by_module': {},
                'tasks_by_type': {},
                'recent_tasks': []
            }
            
            # Calculate success rate
            if stats['total_tasks'] > 0:
                stats['success_rate'] = (stats['completed_tasks'] / stats['total_tasks']) * 100
            
            # Calculate average duration
            completed_tasks = tasks.filter(
                status='completed',
                started_at__isnull=False,
                completed_at__isnull=False
            )
            if completed_tasks.exists():
                durations = [
                    (task.completed_at - task.started_at).total_seconds()
                    for task in completed_tasks
                ]
                stats['average_duration'] = sum(durations) / len(durations)
            
            # Tasks by module
            module_stats = tasks.values('module').annotate(count=Count('id'))
            stats['tasks_by_module'] = {item['module']: item['count'] for item in module_stats}
            
            # Tasks by type
            type_stats = tasks.values('task_type').annotate(count=Count('id'))
            stats['tasks_by_type'] = {item['task_type']: item['count'] for item in type_stats}
            
            # Recent tasks
            recent_tasks = tasks.order_by('-created_at')[:10]
            stats['recent_tasks'] = TaskSerializer(recent_tasks, many=True).data
            
            return APIResponse.success(data=stats, message='Task dashboard retrieved successfully', correlation_id=correlation_id)
            
        except Exception as e:
            logger.error(f'Error retrieving task dashboard: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving dashboard', error_id=str(e), correlation_id=get_correlation_id(request))

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a running task"""
        try:
            correlation_id = get_correlation_id(request)
            task = self.get_object()
            
            if task.status not in ['pending', 'running']:
                return APIResponse.bad_request(message='Task cannot be cancelled', error_id='invalid_task_status', correlation_id=correlation_id)
            
            # Update task status
            task.status = 'cancelled'
            task.completed_at = timezone.now()
            task.save(update_fields=['status', 'completed_at'])
            AuditTrail.log(operation=AuditTrail.CANCEL, module='task_management', entity_type='Task', entity_id=task.id, user=request.user, reason=f'Task cancelled by {request.user.username}', request=request)
            
            # Log cancellation
            TaskLog.objects.create(
                task=task,
                level='info',
                message=f"Task cancelled by {request.user.username}",
                data={'cancelled_by': request.user.id}
            )
            
            return APIResponse.success(data=self.get_serializer(task).data, message='Task cancelled successfully', correlation_id=correlation_id)
            
        except Exception as e:
            logger.error(f'Error cancelling task: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error cancelling task', error_id=str(e), correlation_id=get_correlation_id(request))

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """Get task logs"""
        try:
            task = self.get_object()
            logs = task.logs.all().order_by('-timestamp')
            
            # Pagination
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 50))
            start = (page - 1) * page_size
            end = start + page_size
            
            logs_page = logs[start:end]
            serializer = TaskLogSerializer(logs_page, many=True)
            
            return Response({
                'logs': serializer.data,
                'total': logs.count(),
                'page': page,
                'page_size': page_size
            })
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def status(self, request):
        """Get task status by task_id"""
        try:
            task_id = request.query_params.get('task_id')
            if not task_id:
                return Response(
                    {'error': 'task_id parameter required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                task = Task.objects.get(task_id=task_id)
                serializer = TaskSerializer(task)
                return Response(serializer.data)
            except Task.DoesNotExist:
                return Response(
                    {'error': 'Task not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def cleanup(self, request):
        """Cleanup old tasks"""
        try:
            days_old = int(request.data.get('days_old', 30))
            
            from .tasks import cleanup_old_tasks
            result = cleanup_old_tasks.delay(days_old)
            
            return Response({
                'message': f'Cleanup task queued for tasks older than {days_old} days',
                'task_id': result.id
            })
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TaskTemplateViewSet(BaseModelViewSet):
    """
    Task template management
    """
    queryset = TaskTemplate.objects.filter(is_active=True)
    serializer_class = TaskTemplateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['name', 'title_template', 'description_template']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """Execute a task template"""
        try:
            template = self.get_object()
            input_data = request.data.get('input_data', {})
            
            # Validate input data against schema
            if template.input_schema:
                try:
                    schema = template.input_schema
                    if isinstance(schema, str):
                        schema = json.loads(schema)
                    jsonschema_validate(instance=input_data, schema=schema)
                except ValidationError as ve:
                    return Response(
                        {'error': f'Input validation failed', 'detail': ve.message},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                except Exception as e:
                    return Response(
                        {'error': 'Invalid input schema configuration', 'detail': str(e)},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Create task from template
            from .tasks import generic_task_wrapper
            
            task = generic_task_wrapper.delay(
                task_type=template.task_type,
                title=template.title_template.format(**input_data),
                description=template.description_template.format(**input_data),
                module=template.module,
                user_id=request.user.id,
                function_name=input_data.get('function_name'),
                **input_data.get('args', []),
                **input_data.get('kwargs', {})
            )
            
            return Response({
                'message': 'Task created from template',
                'task_id': task.id
            })
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )