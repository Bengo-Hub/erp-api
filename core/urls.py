# urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UploadData, RegionsViewSet, DepartmentsViewSet, ProjectsViewSet, ProjectCategoryViewSet,
    BankInstitutionViewSet, BankBranchesViewSet, RegionalSettingsViewSet, BrandingSettingsViewSet,
    HealthCheckView, ExecutiveDashboardView, PerformanceDashboardView,
    PerformanceMetricsView, DatabaseOptimizationView, CacheManagementView,
    SystemHealthView, BackgroundJobManagementView, ImageOptimizationView,
    CDNManagementView, ResponsiveImagesView, LoadTestingView
)

router = DefaultRouter()
router.register(r'regions', RegionsViewSet)
router.register(r'projects', ProjectsViewSet)
router.register(r'project-categories', ProjectCategoryViewSet)
router.register(r'departments', DepartmentsViewSet)
router.register(r'banks', BankInstitutionViewSet)
router.register(r'bank-branches', BankBranchesViewSet)
router.register(r'regional-settings', RegionalSettingsViewSet, basename='regional-settings')
router.register(r'branding-settings', BrandingSettingsViewSet, basename='branding-settings')

urlpatterns = [
    path('', include(router.urls)),
    path('uploads/', UploadData.as_view(), name='uploads'),
    path('health/', HealthCheckView.as_view(), name='health-check'),
    # Banner endpoint moved to campaigns app
    # Use: /api/v1/campaigns/active_banners/
    
    # Dashboard endpoints
    path('dashboard/executive/', ExecutiveDashboardView.as_view(), name='executive-dashboard'),
    path('dashboard/performance/', PerformanceDashboardView.as_view(), name='performance-dashboard'),
    
    # Performance monitoring endpoints
    path('performance/metrics/', PerformanceMetricsView.as_view(), name='performance-metrics'),
    path('performance/optimization/', DatabaseOptimizationView.as_view(), name='database-optimization'),
    path('performance/cache/', CacheManagementView.as_view(), name='cache-management'),
    path('performance/system-health/', SystemHealthView.as_view(), name='system-health'),
    
    # Background job management endpoints
    path('background-jobs/', BackgroundJobManagementView.as_view(), name='background-jobs'),
    
    # Image optimization and CDN endpoints
    path('image-optimization/', ImageOptimizationView.as_view(), name='image-optimization'),
    path('cdn-management/', CDNManagementView.as_view(), name='cdn-management'),
    path('responsive-images/', ResponsiveImagesView.as_view(), name='responsive-images'),
    
    # Load testing endpoints
    path('load-testing/', LoadTestingView.as_view(), name='load-testing'),
]