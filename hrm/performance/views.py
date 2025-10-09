from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Count, Avg, Q
from datetime import datetime, timedelta

from .models import (
    MetricCategory, PerformanceMetric, EmployeeMetric,
    MetricTarget, PerformanceReview, ReviewMetric
)
from .serializers import (
    MetricCategorySerializer, PerformanceMetricSerializer,
    EmployeeMetricSerializer, MetricTargetSerializer,
    PerformanceReviewSerializer, ReviewMetricSerializer,
    MetricCategoryCreateSerializer, PerformanceMetricCreateSerializer,
    EmployeeMetricCreateSerializer, MetricTargetCreateSerializer,
    PerformanceReviewCreateSerializer, ReviewMetricCreateSerializer
)

class MetricCategoryViewSet(viewsets.ModelViewSet):
    queryset = MetricCategory.objects.all()
    serializer_class = MetricCategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'order', 'created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return MetricCategoryCreateSerializer
        return MetricCategorySerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get only active categories"""
        categories = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer(categories, many=True)
        return Response(serializer.data)

class PerformanceMetricViewSet(viewsets.ModelViewSet):
    queryset = PerformanceMetric.objects.all()
    serializer_class = PerformanceMetricSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['category', 'metric_type', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PerformanceMetricCreateSerializer
        return PerformanceMetricSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def by_category(self, request):
        """Get metrics by category ID"""
        category_id = request.query_params.get('category')
        if not category_id:
            return Response({'error': 'category parameter is required'}, status=400)
        
        metrics = self.get_queryset().filter(category_id=category_id, is_active=True)
        serializer = self.get_serializer(metrics, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get only active metrics"""
        metrics = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer(metrics, many=True)
        return Response(serializer.data)

class EmployeeMetricViewSet(viewsets.ModelViewSet):
    queryset = EmployeeMetric.objects.all()
    serializer_class = EmployeeMetricSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employee', 'metric', 'metric__category']
    search_fields = ['employee__user__first_name', 'employee__user__last_name', 'metric__name']
    ordering_fields = ['date_recorded', 'created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return EmployeeMetricCreateSerializer
        return EmployeeMetricSerializer

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)

    @action(detail=False, methods=['get'])
    def by_employee(self, request):
        """Get metrics for a specific employee"""
        employee_id = request.query_params.get('employee')
        if not employee_id:
            return Response({'error': 'employee parameter is required'}, status=400)
        
        metrics = self.get_queryset().filter(employee_id=employee_id)
        serializer = self.get_serializer(metrics, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_metric(self, request):
        """Get all employee values for a specific metric"""
        metric_id = request.query_params.get('metric')
        if not metric_id:
            return Response({'error': 'metric parameter is required'}, status=400)
        
        metrics = self.get_queryset().filter(metric_id=metric_id)
        serializer = self.get_serializer(metrics, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        """Get analytics for employee metrics"""
        employee_id = request.query_params.get('employee')
        metric_id = request.query_params.get('metric')
        period = request.query_params.get('period', 'month')  # week, month, quarter, year
        
        # Calculate date range
        today = datetime.now().date()
        if period == 'week':
            start_date = today - timedelta(days=7)
        elif period == 'month':
            start_date = today - timedelta(days=30)
        elif period == 'quarter':
            start_date = today - timedelta(days=90)
        elif period == 'year':
            start_date = today - timedelta(days=365)
        else:
            start_date = today - timedelta(days=30)
        
        queryset = self.get_queryset().filter(date_recorded__gte=start_date)
        
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        if metric_id:
            queryset = queryset.filter(metric_id=metric_id)
        
        # Calculate analytics
        total_records = queryset.count()
        avg_value = queryset.aggregate(avg=Avg('numeric_value'))['avg'] or 0
        
        # Group by metric for detailed analytics
        metric_analytics = queryset.values('metric__name').annotate(
            count=Count('id'),
            avg_value=Avg('numeric_value')
        )
        
        return Response({
            'period': period,
            'start_date': start_date,
            'end_date': today,
            'total_records': total_records,
            'average_value': avg_value,
            'metric_analytics': metric_analytics
        })

class MetricTargetViewSet(viewsets.ModelViewSet):
    queryset = MetricTarget.objects.all()
    serializer_class = MetricTargetSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employee', 'metric', 'is_active']
    search_fields = ['employee__user__first_name', 'employee__user__last_name', 'metric__name']
    ordering_fields = ['period_start', 'created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return MetricTargetCreateSerializer
        return MetricTargetSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def by_employee(self, request):
        """Get targets for a specific employee"""
        employee_id = request.query_params.get('employee')
        if not employee_id:
            return Response({'error': 'employee parameter is required'}, status=400)
        
        targets = self.get_queryset().filter(employee_id=employee_id, is_active=True)
        serializer = self.get_serializer(targets, many=True)
        return Response(serializer.data)

class PerformanceReviewViewSet(viewsets.ModelViewSet):
    queryset = PerformanceReview.objects.all()
    serializer_class = PerformanceReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employee', 'status', 'reviewer']
    search_fields = ['employee__user__first_name', 'employee__user__last_name', 'title']
    ordering_fields = ['review_date', 'created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PerformanceReviewCreateSerializer
        return PerformanceReviewSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def add_metric(self, request, pk=None):
        """Add a metric to a performance review"""
        review = self.get_object()
        metric_data = request.data
        metric_data['review'] = review.id
        
        serializer = ReviewMetricCreateSerializer(data=metric_data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Submit a performance review"""
        review = self.get_object()
        review.status = 'completed'
        review.save()
        return Response({'status': 'review submitted'})

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a performance review"""
        review = self.get_object()
        review.status = 'approved'
        review.save()
        return Response({'status': 'review approved'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a performance review"""
        review = self.get_object()
        review.status = 'rejected'
        review.save()
        return Response({'status': 'review rejected'})

class ReviewMetricViewSet(viewsets.ModelViewSet):
    queryset = ReviewMetric.objects.all()
    serializer_class = ReviewMetricSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['review', 'metric']
    search_fields = ['metric__name']
    ordering_fields = ['created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ReviewMetricCreateSerializer
        return ReviewMetricSerializer
