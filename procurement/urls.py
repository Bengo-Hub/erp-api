"""
Procurement module URL configuration.
"""
from django.urls import path, include
from .services.analytics_views import procurement_analytics, procurement_dashboard
from .services.reports_views import (
    supplier_analysis,
    spend_analysis
)

urlpatterns = [
    # Procurement Analytics Endpoints
    path('analytics/', procurement_analytics, name='procurement-analytics'),
    path('dashboard/', procurement_dashboard, name='procurement-dashboard'),
    
    # Procurement Reports Endpoints
    path('reports/supplier-analysis/', supplier_analysis, name='procurement-supplier-analysis'),
    path('reports/spend-analysis/', spend_analysis, name='procurement-spend-analysis'),
    
    # Include submodule URLs
    path('', include('procurement.purchases.urls')),
    path('', include('procurement.requisitions.urls')),
    path('', include('procurement.orders.urls')),
    path('', include('procurement.contracts.urls')),
    path('', include('procurement.supplier_performance.urls')),
]
