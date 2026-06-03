from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ExchangeRateAPISettingsViewSet, integration_health_check

# Payment/KRA/webhook/pos-bridge integrations moved to treasury-api / pos-api.
# The ERP retains only the generic event outbox + FX (exchange-rate) integration.
router = DefaultRouter()
router.register(r'exchange-rate-api', ExchangeRateAPISettingsViewSet, basename='exchange-rate-api')

urlpatterns = [
    path('', include(router.urls)),
    path('health/', integration_health_check, name='integration-health'),
]
