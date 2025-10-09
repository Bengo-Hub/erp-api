from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'addresses', views.AddressBookViewSet, basename='addresses')
router.register(r'delivery-regions', views.DeliveryRegionViewSet, basename='delivery-regions')
router.register(r'validations', views.AddressValidationViewSet, basename='address-validations')

urlpatterns = [
    path('', include(router.urls)),
]
