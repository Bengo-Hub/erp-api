from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    MetricCategoryViewSet, PerformanceMetricViewSet,
    EmployeeMetricViewSet, MetricTargetViewSet,
    PerformanceReviewViewSet, ReviewMetricViewSet
)

router = DefaultRouter()
router.register(r'metric-categories', MetricCategoryViewSet)
router.register(r'performance-metrics', PerformanceMetricViewSet)
router.register(r'employee-metrics', EmployeeMetricViewSet)
router.register(r'metric-targets', MetricTargetViewSet)
router.register(r'performance-reviews', PerformanceReviewViewSet)
router.register(r'review-metrics', ReviewMetricViewSet)

urlpatterns = [
    path('', include(router.urls)),  # Remove the extra 'performance/' prefix
]
