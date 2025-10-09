
from django.urls import path, include
from rest_framework import routers
from .views import *

router = routers.DefaultRouter()
router.register(r'stock', InventoryViewSet,basename='stock')
router.register(r'units', UnitViewSet,basename='units')
router.register(r'pos-stock', PosInventoryViewSet,basename='pos_stock')
router.register(r'stocktransactions', StockTransactionViewSet)
router.register(r'stocktransfers', StockTransferViewSet)
router.register(r'stockadjustments', StockAdjustmentViewSet)

from .views import InventoryDashboardView

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/', InventoryDashboardView.as_view(), name='inventory-dashboard'),
]
