from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import InvoiceViewSet, InvoicePaymentViewSet, InvoiceEmailLogViewSet

router = DefaultRouter()
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'invoice-payments', InvoicePaymentViewSet, basename='invoice-payment')
router.register(r'invoice-email-logs', InvoiceEmailLogViewSet, basename='invoice-email-log')

urlpatterns = [
    path('', include(router.urls)),
]

