
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    KRASettingsViewSet, WebhookEndpointViewSet, WebhookEventViewSet
)
# Notification-related views moved to centralized notifications app

# Create router for ViewSets
router = DefaultRouter()
router.register(r'kra-settings', KRASettingsViewSet, basename='kra-settings')
router.register(r'webhook-endpoints', WebhookEndpointViewSet, basename='webhook-endpoints')
router.register(r'webhook-events', WebhookEventViewSet, basename='webhook-events')

urlpatterns = [
    # Include router URLs
    path('', include(router.urls)),
]
