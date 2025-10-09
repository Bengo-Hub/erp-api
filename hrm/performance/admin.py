from django.contrib import admin
from .models import (
    MetricCategory, PerformanceMetric, EmployeeMetric,
    MetricTarget, PerformanceReview, ReviewMetric
)

@admin.register(MetricCategory)
class MetricCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'order', 'is_active', 'created_by', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    ordering = ['order', 'name']
    readonly_fields = ['created_by', 'created_at', 'updated_at']

    def save_model(self, request, obj, form, change):
        if not change:  # Only set created_by on creation
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(PerformanceMetric)
class PerformanceMetricAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'metric_type', 'unit', 'is_active', 'created_by']
    list_filter = ['category', 'metric_type', 'is_active', 'created_at']
    search_fields = ['name', 'description', 'category__name']
    ordering = ['category__order', 'name']
    readonly_fields = ['created_by', 'created_at', 'updated_at']

    def save_model(self, request, obj, form, change):
        if not change:  # Only set created_by on creation
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(EmployeeMetric)
class EmployeeMetricAdmin(admin.ModelAdmin):
    list_display = ['employee', 'metric', 'value', 'date_recorded', 'recorded_by']
    list_filter = ['metric__category', 'metric__metric_type', 'date_recorded', 'created_at']
    search_fields = ['employee__user__first_name', 'employee__user__last_name', 'metric__name']
    ordering = ['-date_recorded', '-created_at']
    readonly_fields = ['recorded_by', 'created_at', 'updated_at']

    def save_model(self, request, obj, form, change):
        if not change:  # Only set recorded_by on creation
            obj.recorded_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(MetricTarget)
class MetricTargetAdmin(admin.ModelAdmin):
    list_display = ['employee', 'metric', 'target_value', 'period_start', 'period_end', 'is_active']
    list_filter = ['metric__category', 'is_active', 'period_start', 'period_end']
    search_fields = ['employee__user__first_name', 'employee__user__last_name', 'metric__name']
    ordering = ['-period_start']
    readonly_fields = ['created_by', 'created_at', 'updated_at']

    def save_model(self, request, obj, form, change):
        if not change:  # Only set created_by on creation
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(PerformanceReview)
class PerformanceReviewAdmin(admin.ModelAdmin):
    list_display = ['employee', 'title', 'review_date', 'status', 'overall_rating', 'reviewer']
    list_filter = ['status', 'review_date', 'created_at']
    search_fields = ['employee__user__first_name', 'employee__user__last_name', 'title']
    ordering = ['-review_date', '-created_at']
    readonly_fields = ['created_by', 'created_at', 'updated_at']

    def save_model(self, request, obj, form, change):
        if not change:  # Only set created_by on creation
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(ReviewMetric)
class ReviewMetricAdmin(admin.ModelAdmin):
    list_display = ['review', 'metric', 'value', 'rating']
    list_filter = ['metric__category', 'metric__metric_type', 'created_at']
    search_fields = ['review__title', 'metric__name']
    ordering = ['review__review_date', 'metric__category__order']
    readonly_fields = ['created_at', 'updated_at']
