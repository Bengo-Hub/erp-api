from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'orders', views.BaseOrderViewSet, basename='base-orders')
router.register(r'order-items', views.OrderItemViewSet, basename='order-items')
router.register(r'order-payments', views.OrderPaymentViewSet, basename='order-payments')

urlpatterns = [
    path('', include(router.urls)),
]
