from rest_framework.routers import DefaultRouter
from .views import ContractViewSet, ContractOrderLinkViewSet


router = DefaultRouter()
router.register(r'contracts', ContractViewSet, basename='contracts')
router.register(r'contract-order-links', ContractOrderLinkViewSet, basename='contract-order-links')

urlpatterns = router.urls


