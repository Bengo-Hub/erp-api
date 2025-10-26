"""
E-commerce module URL configuration.
"""
from django.urls import path, include
from .services.reports_views import (
    sales_dashboard,
    product_performance,
    customer_analysis,
    inventory_management,
    ecommerce_reports_suite
)

urlpatterns = [
    # E-commerce Analytics Endpoints (Separate module)
    path('analytics/', include('ecommerce.analytics.urls')),
    
    # E-commerce Reports Endpoints
    path('reports/sales-dashboard/', sales_dashboard, name='ecommerce-sales-dashboard'),
    path('reports/product-performance/', product_performance, name='ecommerce-product-performance'),
    path('reports/customer-analysis/', customer_analysis, name='ecommerce-customer-analysis'),
    path('reports/inventory-management/', inventory_management, name='ecommerce-inventory-management'),
    path('reports/suite/', ecommerce_reports_suite, name='ecommerce-reports-suite'),
    
    # Include submodule URLs
    path('products/', include('ecommerce.product.urls')),
    path('cart/', include('ecommerce.cart.urls')),
    path('orders/', include('ecommerce.order.urls')),
    path('inventory/', include('ecommerce.stockinventory.urls')),
    path('pos/', include('ecommerce.pos.urls')),
    path('vendors/', include('ecommerce.vendor.urls')),
]
