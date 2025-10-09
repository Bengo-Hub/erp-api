from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AssetCategoryViewSet, AssetViewSet,
    AssetDepreciationViewSet, AssetInsuranceViewSet, AssetAuditViewSet,
    AssetReservationViewSet, AssetTransferViewSet, AssetMaintenanceViewSet,
    AssetDisposalViewSet, AssetDashboardViewSet
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
    path('assets/', include(router.urls)),
    path('assets/dashboard/', AssetDashboardViewSet.as_view({'get': 'dashboard'}), name='asset-dashboard'),
]
