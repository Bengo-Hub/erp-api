from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AccountTypesViewSet, PaymentAccountsViewSet, TransactionViewSet, VoucherViewSet

router = DefaultRouter()
router.register(r'accounttypes', AccountTypesViewSet)
router.register(r'paymentaccounts', PaymentAccountsViewSet)
router.register(r'transactions', TransactionViewSet)
router.register(r'vouchers', VoucherViewSet)

urlpatterns = [
    path('', include(router.urls)),
]