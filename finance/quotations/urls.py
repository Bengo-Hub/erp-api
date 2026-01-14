from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import QuotationViewSet, QuotationEmailLogViewSet, PublicQuotationView, PublicQuotationPDFView

router = DefaultRouter()
router.register(r'quotations', QuotationViewSet, basename='quotation')
router.register(r'quotation-email-logs', QuotationEmailLogViewSet, basename='quotation-email-log')

urlpatterns = [
    path('', include(router.urls)),
    # Public API endpoints for accessing quotations via share token
    path('public/quotation/<int:quotation_id>/<str:token>/', PublicQuotationView.as_view(), name='public-quotation-api'),
    path('public/quotation/<int:quotation_id>/<str:token>/pdf/', PublicQuotationPDFView.as_view(), name='public-quotation-pdf'),
]

