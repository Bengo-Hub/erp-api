from rest_framework.routers import DefaultRouter
from .views import JobPostingViewSet, CandidateViewSet, ApplicationViewSet
from .onboarding_api import EmployeeOnboardingViewSet, OnboardingTaskViewSet


router = DefaultRouter()
router.register(r'jobs', JobPostingViewSet, basename='recruitment-jobs')
router.register(r'candidates', CandidateViewSet, basename='recruitment-candidates')
router.register(r'applications', ApplicationViewSet, basename='recruitment-applications')
router.register(r'onboarding', EmployeeOnboardingViewSet, basename='recruitment-onboarding')
router.register(r'onboarding-tasks', OnboardingTaskViewSet, basename='recruitment-onboarding-tasks')

urlpatterns = router.urls


