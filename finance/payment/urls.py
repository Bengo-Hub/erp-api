"""
URL routing for the centralized payment service
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PaymentViewSet,
    POSPaymentViewSet,
    PaymentTransactionViewSet,
    PaymentRefundViewSet,
    PaymentMethodViewSet,
    BillingDocumentViewSet
)
from .views import (
    MpesaPaymentView,
    MpesaCallbackView,
    ProcessPaymentView,
    SplitPaymentView,
    get_payment_accounts,
)
from .public_views import (
    PublicInvoicePaymentView,
    PaystackWebhookView,
    PaystackVerifyPaymentView,
    PublicPaymentMethodsView,
)

router = DefaultRouter()
router.register(r'methods', PaymentMethodViewSet, basename='payment-method')
router.register(r'payments', PaymentViewSet, basename='payment')
router.register(r'pos-payments', POSPaymentViewSet, basename='pos-payment')
router.register(r'transactions', PaymentTransactionViewSet, basename='payment-transaction')
router.register(r'refunds', PaymentRefundViewSet, basename='payment-refund')
router.register(r'documents', BillingDocumentViewSet, basename='billing-document')

urlpatterns = [
    path('', include(router.urls)),
    # Non-viewset API endpoints
    path('process/', ProcessPaymentView.as_view(), name='finance-process-payment'),
    path('split/', SplitPaymentView.as_view(), name='finance-split-payment'),
    path('accounts/', get_payment_accounts, name='finance-payment-accounts'),
    # M-Pesa specific endpoints
    path('mpesa/process/', MpesaPaymentView.as_view(), name='finance-mpesa-process'),
    path('mpesa/callback/', MpesaCallbackView.as_view(), name='finance-mpesa-callback'),
    # Public payment endpoints (no authentication required)
    path('public/invoice/<int:invoice_id>/<str:token>/pay/', PublicInvoicePaymentView.as_view(), name='public-invoice-payment'),
    path('public/invoice/<int:invoice_id>/<str:token>/methods/', PublicPaymentMethodsView.as_view(), name='public-payment-methods'),
    # Paystack webhooks and verification
    path('paystack/webhook/', PaystackWebhookView.as_view(), name='paystack-webhook'),
    path('paystack/verify/<str:reference>/', PaystackVerifyPaymentView.as_view(), name='paystack-verify'),
]
