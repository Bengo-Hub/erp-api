from rest_framework.routers import DefaultRouter
from .views import (
    TrainingCourseViewSet,
    TrainingEnrollmentViewSet,
    TrainingEvaluationViewSet,
)


router = DefaultRouter()
router.register(r'courses', TrainingCourseViewSet, basename='training-courses')
router.register(r'enrollments', TrainingEnrollmentViewSet, basename='training-enrollments')
router.register(r'evaluations', TrainingEvaluationViewSet, basename='training-evaluations')

urlpatterns = router.urls


