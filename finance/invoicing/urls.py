from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    InvoiceViewSet, InvoicePaymentViewSet, InvoiceEmailLogViewSet,
    PublicInvoiceView, PublicInvoicePDFView, CreditNoteViewSet, DebitNoteViewSet,
    DeliveryNoteViewSet, ProformaInvoiceViewSet
)

router = DefaultRouter()
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'invoice-payments', InvoicePaymentViewSet, basename='invoice-payment')
router.register(r'invoice-email-logs', InvoiceEmailLogViewSet, basename='invoice-email-log')
router.register(r'credit-notes', CreditNoteViewSet, basename='credit-note')
router.register(r'debit-notes', DebitNoteViewSet, basename='debit-note')
router.register(r'delivery-notes', DeliveryNoteViewSet, basename='delivery-note')
router.register(r'proforma-invoices', ProformaInvoiceViewSet, basename='proforma-invoice')

urlpatterns = [
    path('', include(router.urls)),
    # Public API endpoints for accessing invoices via share token
    path('public/invoice/<int:invoice_id>/<str:token>/', PublicInvoiceView.as_view(), name='public-invoice-api'),
    path('public/invoice/<int:invoice_id>/<str:token>/pdf/', PublicInvoicePDFView.as_view(), name='public-invoice-pdf'),
]


