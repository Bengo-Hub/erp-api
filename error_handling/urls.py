"""
URLs for centralized error handling
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ErrorViewSet, ErrorLogViewSet, ErrorPatternViewSet

router = DefaultRouter()
router.register(r'errors', ErrorViewSet)
router.register(r'error-logs', ErrorLogViewSet)
router.register(r'error-patterns', ErrorPatternViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
