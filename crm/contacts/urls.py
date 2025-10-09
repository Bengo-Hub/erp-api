
from django.urls import path, include
from rest_framework import routers
from .views import *

router = routers.DefaultRouter()
#router.register('suppliers', SupplierViewSet)
router.register('contacts', ContactsViewSet)
router.register('customer_groups', CustomerGroupViewSet)


urlpatterns = [
    path('', include(router.urls)),
    path('top-products/', top_products),
    path('top-buyers/', top_buyers),
    path('sales-analytics/', SaleAnalyticsViewSet.as_view({'get': 'list'})),
]
