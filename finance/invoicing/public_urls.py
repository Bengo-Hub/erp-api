"""
Public URLs for invoicing and quotations modules (no authentication required)
These are meant to be included at the root level, not under /api/v1/
"""
from django.urls import path
from finance.invoicing import views as invoicing_views
from finance.quotations.views import PublicQuotationView

urlpatterns = [
    path('public/invoice/<int:invoice_id>/<str:token>/', invoicing_views.PublicInvoiceView.as_view(), name='public-invoice'),
    path('public/quotation/<int:quotation_id>/<str:token>/', PublicQuotationView.as_view(), name='public-quotation'),
]
