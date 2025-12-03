from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import QuotationViewSet, QuotationEmailLogViewSet

router = DefaultRouter()
router.register(r'quotations', QuotationViewSet, basename='quotation')
router.register(r'quotation-email-logs', QuotationEmailLogViewSet, basename='quotation-email-log')

urlpatterns = [
    path('', include(router.urls)),
]

