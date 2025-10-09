from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'formulas', views.ProductFormulaViewSet)
router.register(r'ingredients', views.FormulaIngredientViewSet)
router.register(r'batches', views.ProductionBatchViewSet)
router.register(r'quality-checks', views.QualityCheckViewSet)
router.register(r'analytics', views.ManufacturingAnalyticsViewSet)
router.register(r'finished-products', views.FinishedProductViewSet, basename='finished-products')
router.register(r'raw-materials', views.RawMaterialViewSet, basename='raw-materials')

urlpatterns = [
    path('', include(router.urls)),
]
