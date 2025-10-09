"""
URLs for centralized caching
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CacheViewSet

router = DefaultRouter()
router.register(r'cache', CacheViewSet, basename='cache')

urlpatterns = [
    path('', include(router.urls)),
]
