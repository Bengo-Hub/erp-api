from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CustomerAnalyticsViewSet, SalesForecastViewSet, 
    CustomerSegmentViewSet, AnalyticsSnapshotViewSet
)

router = DefaultRouter()
router.register(r'customer-analytics', CustomerAnalyticsViewSet, basename='customer-analytics')
router.register(r'sales-forecasts', SalesForecastViewSet, basename='sales-forecasts')
router.register(r'customer-segments', CustomerSegmentViewSet, basename='customer-segments')
router.register(r'analytics-snapshots', AnalyticsSnapshotViewSet, basename='analytics-snapshots')

urlpatterns = [
    path('', include(router.urls)),
]
