from django.urls import path, include
from rest_framework import routers
from .views import (
    OrderViewSet, OrderItemViewSet, checkout, guest_checkout, 
    get_customer_orders, get_order_details, track_order, 
    cancel_order, add_order_payment, download_order_invoice
)
# Legacy utilities are deprecated after centralization

# Routers provide an easy way of automatically determining the URL conf.
router = routers.DefaultRouter()
router.register('orders', OrderViewSet)
router.register('orderitems', OrderItemViewSet)

# Wire up our API using automatic URL routing.
urlpatterns = [
    path('', include(router.urls)),
    
    # Order APIs
    path('checkout/', checkout, name='order-checkout'),
    
    # Customer-facing APIs
    path('guest-checkout/', guest_checkout, name='guest-checkout'),
    path('customer-orders/', get_customer_orders, name='customer-orders'),
    path('customer-orders/<str:order_id>/', get_order_details, name='customer-order-details'),
    path('customer-orders/<str:order_id>/track/', track_order, name='track-order'),
    path('customer-orders/<str:order_id>/cancel/', cancel_order, name='cancel-order'),
    path('customer-orders/<str:order_id>/payment/', add_order_payment, name='add-order-payment'),
    path('customer-orders/<str:order_id>/invoice/', download_order_invoice, name='download-invoice'),
    
    # Legacy endpoints removed (migrated to centralized flows)
]
