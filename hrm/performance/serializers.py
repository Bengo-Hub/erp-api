from rest_framework import serializers
from .models import (
    MetricCategory, PerformanceMetric, EmployeeMetric,
    MetricTarget, PerformanceReview, ReviewMetric
)
from hrm.employees.serializers import EmployeeSerializer
from authmanagement.serializers import UserSerializer

class MetricCategorySerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    metrics_count = serializers.SerializerMethodField()

    class Meta:
        model = MetricCategory
        fields = [
            'id', 'name', 'description', 'order', 'is_active',
            'created_by', 'created_at', 'updated_at', 'metrics_count'
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

    def get_metrics_count(self, obj):
        return obj.metrics.filter(is_active=True).count()

class PerformanceMetricSerializer(serializers.ModelSerializer):
    category = MetricCategorySerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    metric_type_display = serializers.CharField(source='metric_type_display', read_only=True)

    class Meta:
        model = PerformanceMetric
        fields = [
            'id', 'category', 'name', 'description', 'metric_type',
            'metric_type_display', 'unit', 'min_value', 'max_value',
            'target_value', 'is_active', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

class EmployeeMetricSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    metric = PerformanceMetricSerializer(read_only=True)
    recorded_by = UserSerializer(read_only=True)

    class Meta:
        model = EmployeeMetric
        fields = [
            'id', 'employee', 'metric', 'value', 'numeric_value',
            'date_recorded', 'period_start', 'period_end', 'notes',
            'recorded_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['recorded_by', 'created_at', 'updated_at']

class MetricTargetSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    metric = PerformanceMetricSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = MetricTarget
        fields = [
            'id', 'employee', 'metric', 'target_value', 'period_start',
            'period_end', 'is_active', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

class ReviewMetricSerializer(serializers.ModelSerializer):
    metric = PerformanceMetricSerializer(read_only=True)

    class Meta:
        model = ReviewMetric
        fields = [
            'id', 'metric', 'value', 'rating', 'comments',
            'created_at', 'updated_at'
        ]

class PerformanceReviewSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    reviewer = EmployeeSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    review_metrics = ReviewMetricSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PerformanceReview
        fields = [
            'id', 'employee', 'title', 'description', 'review_date',
            'status', 'status_display', 'overall_rating', 'comments',
            'reviewer', 'created_by', 'created_at', 'updated_at',
            'review_metrics'
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

# Nested serializers for creating/updating
class MetricCategoryCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricCategory
        fields = ['name', 'description', 'order', 'is_active']

class PerformanceMetricCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerformanceMetric
        fields = [
            'category', 'name', 'description', 'metric_type',
            'unit', 'min_value', 'max_value', 'target_value', 'is_active'
        ]

class EmployeeMetricCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeMetric
        fields = [
            'employee', 'metric', 'value', 'date_recorded',
            'period_start', 'period_end', 'notes'
        ]

class MetricTargetCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricTarget
        fields = [
            'employee', 'metric', 'target_value', 'period_start',
            'period_end', 'is_active'
        ]

class PerformanceReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerformanceReview
        fields = [
            'employee', 'title', 'description', 'review_date',
            'status', 'overall_rating', 'comments', 'reviewer'
        ]

class ReviewMetricCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewMetric
        fields = ['metric', 'value', 'rating', 'comments']
