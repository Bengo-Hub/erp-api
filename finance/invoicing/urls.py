from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    InvoiceViewSet, InvoicePaymentViewSet, InvoiceEmailLogViewSet,
    PublicInvoiceView
)

router = DefaultRouter()
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'invoice-payments', InvoicePaymentViewSet, basename='invoice-payment')
router.register(r'invoice-email-logs', InvoiceEmailLogViewSet, basename='invoice-email-log')

urlpatterns = [
    path('', include(router.urls)),
    # Public API endpoint for accessing invoices via share token
    path('public/invoice/<int:invoice_id>/<str:token>/', PublicInvoiceView.as_view(), name='public-invoice-api'),
]


