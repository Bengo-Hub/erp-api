from rest_framework.routers import DefaultRouter
from .views import JobPostingViewSet, CandidateViewSet, ApplicationViewSet


router = DefaultRouter()
router.register(r'jobs', JobPostingViewSet, basename='recruitment-jobs')
router.register(r'candidates', CandidateViewSet, basename='recruitment-candidates')
router.register(r'applications', ApplicationViewSet, basename='recruitment-applications')

urlpatterns = router.urls


