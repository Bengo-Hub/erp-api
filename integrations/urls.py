
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    KRASettingsViewSet, WebhookEndpointViewSet, WebhookEventViewSet, MpesaSettingsViewSet
)
from .health_views import (
    integration_health_check, mpesa_health_check, kra_health_check,
    sms_health_check, email_health_check, clear_integration_cache,
    integration_summary
)
# Notification-related views moved to centralized notifications app

# Create router for ViewSets
router = DefaultRouter()
router.register(r'kra-settings', KRASettingsViewSet, basename='kra-settings')
router.register(r'mpesa-settings', MpesaSettingsViewSet, basename='mpesa-settings')
router.register(r'webhook-endpoints', WebhookEndpointViewSet, basename='webhook-endpoints')
router.register(r'webhook-events', WebhookEventViewSet, basename='webhook-events')

urlpatterns = [
    # Include router URLs
    path('', include(router.urls)),
    
    # Health check endpoints
    path('health/', integration_health_check, name='integration-health'),
    path('health/mpesa/', mpesa_health_check, name='mpesa-health'),
    path('health/kra/', kra_health_check, name='kra-health'),
    path('health/sms/', sms_health_check, name='sms-health'),
    path('health/email/', email_health_check, name='email-health'),
    path('cache/clear/', clear_integration_cache, name='clear-integration-cache'),
    path('summary/', integration_summary, name='integration-summary'),
]
