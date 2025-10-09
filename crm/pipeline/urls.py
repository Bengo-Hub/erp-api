from rest_framework.routers import DefaultRouter
from .views import PipelineStageViewSet, DealViewSet, OpportunityViewSet


router = DefaultRouter()
router.register(r'stages', PipelineStageViewSet, basename='pipeline-stages')
router.register(r'deals', DealViewSet, basename='pipeline-deals')
router.register(r'opportunities', OpportunityViewSet, basename='pipeline-opportunities')

urlpatterns = router.urls


