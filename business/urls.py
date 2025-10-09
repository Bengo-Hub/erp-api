
from django.urls import path, include
from rest_framework import routers
from .views import *

router = routers.DefaultRouter()
# Business and settings endpoints
router.register(r'locations', BusinessLocationViewSet)
router.register(r'branches', BranchesViewSet)
router.register(r'business', BussinessViewSet)
router.register(r'product-settings', ProductSettingsViewSet)
router.register(r'sale-settings', SaleSettingsViewSet)
router.register(r'prefix-settings', PrefixSettingsViewSet)
router.register(r'tax-rates', TaxRatesViewSet)
router.register(r'service-types', ServiceTypesViewSet)

# Address management endpoints
router.register(r'delivery-regions', DeliveryRegionsViewSet)
router.register(r'pickup-stations', PickupStationsViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
