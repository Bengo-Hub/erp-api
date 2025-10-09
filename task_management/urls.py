"""
URLs for centralized task management
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TaskViewSet, TaskTemplateViewSet

router = DefaultRouter()
router.register(r'tasks', TaskViewSet)
router.register(r'task-templates', TaskTemplateViewSet)

urlpatterns = [
    path('', include(router.urls)),
]