from django.urls import path, include
from rest_framework import routers
from .views import TaxCategoryViewSet, TaxViewSet, TaxGroupViewSet, TaxPeriodViewSet

router = routers.DefaultRouter()
router.register(r'categories', TaxCategoryViewSet)
router.register(r'rates', TaxViewSet)
router.register(r'groups', TaxGroupViewSet)
router.register(r'periods', TaxPeriodViewSet)


urlpatterns = [
    path('', include(router.urls)),
]