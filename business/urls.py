
from django.urls import path, include
from rest_framework import routers
from .views import *
from .views import public_branding

router = routers.DefaultRouter()
# Business settings at root (api/v1/business/)
router.register(r'settings', BussinessViewSet, basename='business')
# Other business endpoints
router.register(r'locations', BusinessLocationViewSet)
router.register(r'branches', BranchesViewSet)
router.register(r'product-settings', ProductSettingsViewSet)
router.register(r'sale-settings', SaleSettingsViewSet)
router.register(r'prefix-settings', PrefixSettingsViewSet)
router.register(r'document-sequences', DocumentSequenceViewSet)
# Tax rates moved to finance.taxes module - use /api/v1/finance/taxes/rates/
router.register(r'service-types', ServiceTypesViewSet)

# Address management endpoints
router.register(r'delivery-regions', DeliveryRegionsViewSet)
router.register(r'pickup-stations', PickupStationsViewSet)

urlpatterns = [
    # Public branding endpoint (no auth required) — for login page tenant branding
    path('public-branding/', public_branding, name='public-branding'),
    path('', include(router.urls)),
]
