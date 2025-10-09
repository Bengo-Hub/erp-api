from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ExpenseCategoryViewSet, PaymentAccountViewSet, ExpenseViewSet, PaymentViewSet

router = DefaultRouter()
router.register(r'expensecategories', ExpenseCategoryViewSet)
router.register(r'paymentaccounts', PaymentAccountViewSet)
router.register(r'expenses', ExpenseViewSet)
router.register(r'payments', PaymentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
