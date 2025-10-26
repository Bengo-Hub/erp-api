from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .services.analytics_views import manufacturing_analytics, manufacturing_dashboard
from .services.reports_views import (
    production_report,
    quality_report
)

router = DefaultRouter()
router.register(r'formulas', views.ProductFormulaViewSet)
router.register(r'ingredients', views.FormulaIngredientViewSet)
router.register(r'batches', views.ProductionBatchViewSet)
router.register(r'quality-checks', views.QualityCheckViewSet)
router.register(r'finished-products', views.FinishedProductViewSet, basename='finished-products')
router.register(r'raw-materials', views.RawMaterialViewSet, basename='raw-materials')

urlpatterns = [
    # Manufacturing Analytics Endpoints
    path('analytics/', manufacturing_analytics, name='manufacturing-analytics'),
    path('dashboard/', manufacturing_dashboard, name='manufacturing-dashboard'),
    
    # Manufacturing Reports Endpoints
    path('reports/production/', production_report, name='manufacturing-production'),
    path('reports/quality/', quality_report, name='manufacturing-quality'),
    
    # Include router URLs
    path('', include(router.urls)),
]
