from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AppraisalCycleViewSet, AppraisalTemplateViewSet,
    AppraisalQuestionViewSet, AppraisalViewSet,
    AppraisalResponseViewSet, GoalViewSet,
    GoalProgressViewSet
)

router = DefaultRouter()
router.register(r'cycles', AppraisalCycleViewSet)
router.register(r'templates', AppraisalTemplateViewSet)
router.register(r'questions', AppraisalQuestionViewSet)
router.register(r'appraisals', AppraisalViewSet)
router.register(r'responses', AppraisalResponseViewSet)
router.register(r'goals', GoalViewSet)
router.register(r'goal-progress', GoalProgressViewSet)

urlpatterns = [
    path('', include(router.urls)),  # Remove the extra 'appraisals/' prefix
] 