from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CampaignViewSet, CampaignPerformanceViewSet

router = DefaultRouter()
router.register(r'campaigns', CampaignViewSet, basename='campaign')
router.register(r'performance', CampaignPerformanceViewSet, basename='campaign-performance')

urlpatterns = [
    path('', include(router.urls)),
]
