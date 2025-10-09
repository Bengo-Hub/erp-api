"""
Centralized error handling views for all ERP modules
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

from .models import Error, ErrorLog, ErrorPattern
from .serializers import ErrorSerializer, ErrorLogSerializer, ErrorPatternSerializer
from .filters import ErrorFilter


class ErrorViewSet(viewsets.ModelViewSet):
    """
    Centralized error management for all ERP modules
    """
    queryset = Error.objects.all()
    serializer_class = ErrorSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ErrorFilter
    search_fields = ['title', 'description', 'module', 'error_message']
    ordering_fields = ['occurred_at', 'severity', 'status', 'occurrence_count']
    ordering = ['-occurred_at']

    def get_queryset(self):
        """Filter errors based on user permissions"""
        queryset = super().get_queryset()
        
        # If user is not staff, only show errors they created or are assigned to
        if not self.request.user.is_staff:
            queryset = queryset.filter(
                Q(user=self.request.user) | Q(resolved_by=self.request.user)
            )
        
        return queryset

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Get error dashboard statistics"""
        try:
            # Get date range from query params
            days = int(request.query_params.get('days', 7))
            start_date = timezone.now() - timedelta(days=days)
            
            # Filter errors by date range
            errors = self.get_queryset().filter(occurred_at__gte=start_date)
            
            # Calculate statistics
            stats = {
                'total_errors': errors.count(),
                'open_errors': errors.filter(status='open').count(),
                'resolved_errors': errors.filter(status='resolved').count(),
                'closed_errors': errors.filter(status='closed').count(),
                'critical_errors': errors.filter(severity='critical').count(),
                'high_errors': errors.filter(severity='high').count(),
                'medium_errors': errors.filter(severity='medium').count(),
                'low_errors': errors.filter(severity='low').count(),
                'errors_by_module': {},
                'errors_by_category': {},
                'recent_errors': []
            }
            
            # Errors by module
            module_stats = errors.values('module').annotate(count=Count('id'))
            stats['errors_by_module'] = {item['module']: item['count'] for item in module_stats}
            
            # Errors by category
            category_stats = errors.values('category').annotate(count=Count('id'))
            stats['errors_by_category'] = {item['category']: item['count'] for item in category_stats}
            
            # Recent errors
            recent_errors = errors.order_by('-occurred_at')[:10]
            stats['recent_errors'] = ErrorSerializer(recent_errors, many=True).data
            
            return Response(stats)
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Resolve an error"""
        try:
            error = self.get_object()
            notes = request.data.get('notes', '')
            
            error.resolve(request.user, notes)
            
            return Response({'message': 'Error resolved successfully'})
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Close an error"""
        try:
            error = self.get_object()
            notes = request.data.get('notes', '')
            
            error.close(request.user, notes)
            
            return Response({'message': 'Error closed successfully'})
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """Get error logs"""
        try:
            error = self.get_object()
            logs = error.logs.all().order_by('-timestamp')
            
            # Pagination
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 50))
            start = (page - 1) * page_size
            end = start + page_size
            
            logs_page = logs[start:end]
            serializer = ErrorLogSerializer(logs_page, many=True)
            
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


class ErrorLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Error log management (read-only)
    """
    queryset = ErrorLog.objects.all()
    serializer_class = ErrorLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['message', 'error__title', 'error__module']
    ordering_fields = ['timestamp', 'level']
    ordering = ['-timestamp']


class ErrorPatternViewSet(viewsets.ModelViewSet):
    """
    Error pattern management
    """
    queryset = ErrorPattern.objects.all()
    serializer_class = ErrorPatternSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['name', 'pattern', 'category']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
