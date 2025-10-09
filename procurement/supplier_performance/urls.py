from rest_framework.routers import DefaultRouter
from .views import SupplierPerformanceViewSet


router = DefaultRouter()
router.register(r'supplier-performance', SupplierPerformanceViewSet, basename='supplier-performance')

urlpatterns = router.urls


