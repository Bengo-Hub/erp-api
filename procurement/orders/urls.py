# router urls
from rest_framework.routers import DefaultRouter
from django.urls import path, include
from . import views

router = DefaultRouter()
router.register(r'purchase-orders', views.PurchaseOrderViewSet, basename='purchase-orders')

from .views import ProcurementDashboardView

urlpatterns = [
    path('orders/', include(router.urls)),
    path('dashboard/', ProcurementDashboardView.as_view(), name='procurement-dashboard'),
]