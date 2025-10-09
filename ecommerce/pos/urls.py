from django.urls import path, include
from rest_framework import routers
from .utils import *
from .views import *
from .reports.summary_reports import SalesSummaryReport
from .reports.inventory_reports import StockReports
from .views import (
    POSViewSet, RegisterViewSet, SuspendedSaleViewSet,
    StaffAdvanceSaleViewSet, StaffAdvanceBalanceViewSet,
    get_sale_details, get_sale_payments, process_pos_payment
)

router = routers.DefaultRouter()
router.register(r'transactions', TransactionViewSet)
router.register(r'salesreturns', SalesReturnViewSet, basename='salesreturn')
router.register(r'salesreturns_refunds',SalesReturnRefundViewSet, basename='salesreturns_refunds')
router.register(r'customer_rewards', CustomerRewardViewSet, basename='customer_rewards')
router.register(r'staff-advance-sales', StaffAdvanceSaleViewSet, basename='staff-advance-sales')
router.register(r'staff-advance-balance', StaffAdvanceBalanceViewSet, basename='staff-advance-balance')
router.register(r'suspended-sales', SuspendedSaleViewSet, basename='suspended-sales')
router.register(r'sales', POSViewSet)
router.register(r'registers', RegisterViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('stats/', DashboardAPIView.as_view(), name='dasstats'),
    path('sales/details/<int:id>/', get_sale_details, name='sale_details'),
    path('sale-payments/<int:id>/', get_sale_payments, name='sale_payments'),
    path('process-payment/', process_pos_payment, name='process_pos_payment'),
    #reporting urls
    path('sales/summary/',SalesSummaryReport.as_view(), name='sales_summary'),
    path('stock/summary/',StockReports.as_view(), name='stock_summary'),
]
