
from django.urls import path, include
from rest_framework import routers
from .views import *

router = routers.DefaultRouter()
router.register('vendors', VendorViewSet)


urlpatterns = [
    path('', include(router.urls)),
    # path('add-product/', addProduct),
]
