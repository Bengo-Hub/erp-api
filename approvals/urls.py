from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'workflows', views.ApprovalWorkflowViewSet, basename='approval-workflows')
router.register(r'steps', views.ApprovalStepViewSet, basename='approval-steps')
router.register(r'approvals', views.ApprovalViewSet, basename='approvals')
router.register(r'requests', views.ApprovalRequestViewSet, basename='approval-requests')

urlpatterns = [
    path('', include(router.urls)),
]
