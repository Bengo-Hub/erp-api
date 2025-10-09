# router urls
from rest_framework.routers import DefaultRouter
from django.urls import path, include
from . import views

router = DefaultRouter()
router.register(r'requisitions', views.ProcurementRequestViewSet, basename='requisitions')
router.register(r'user-requests', views.UserRequestViewSet, basename='user-requests')

urlpatterns = [
    path('requisitions/', include(router.urls)),
]