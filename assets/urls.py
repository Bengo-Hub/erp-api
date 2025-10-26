from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AssetCategoryViewSet, AssetViewSet,
    AssetDepreciationViewSet, AssetInsuranceViewSet, AssetAuditViewSet,
    AssetReservationViewSet, AssetTransferViewSet, AssetMaintenanceViewSet,
    AssetDisposalViewSet, AssetDashboardViewSet
)
from .services.analytics_views import assets_analytics, assets_dashboard
from .services.reports_views import (
    inventory_report,
    depreciation_report
)

router = DefaultRouter()
router.register(r'categories', AssetCategoryViewSet)
router.register(r'assets', AssetViewSet)
router.register(r'depreciation', AssetDepreciationViewSet)
router.register(r'insurance', AssetInsuranceViewSet)
router.register(r'audits', AssetAuditViewSet)
router.register(r'reservations', AssetReservationViewSet)
router.register(r'transfers', AssetTransferViewSet)
router.register(r'maintenance', AssetMaintenanceViewSet)
router.register(r'disposals', AssetDisposalViewSet)

urlpatterns = [
    # Assets Analytics Endpoints
    path('analytics/', assets_analytics, name='assets-analytics'),
    path('dashboard/', assets_dashboard, name='assets-dashboard'),
    
    # Assets Reports Endpoints
    path('reports/inventory/', inventory_report, name='assets-inventory'),
    path('reports/depreciation/', depreciation_report, name='assets-depreciation'),
    
    # Include router URLs
    path('assets/', include(router.urls)),
]
