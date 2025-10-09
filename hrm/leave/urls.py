from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LeaveCategoryViewSet,
    LeaveEntitlementViewSet,
    LeaveRequestViewSet,
    LeaveBalanceViewSet,
    LeaveLogViewSet,
    PublicHolidayViewSet,
    leave_analytics,
)

router = DefaultRouter()
router.register(r'categories', LeaveCategoryViewSet)
router.register(r'entitlements', LeaveEntitlementViewSet)
router.register(r'requests', LeaveRequestViewSet)
router.register(r'balances', LeaveBalanceViewSet)
router.register(r'logs', LeaveLogViewSet)
router.register(r'holidays', PublicHolidayViewSet)

urlpatterns = [
    path('', include(router.urls)),  # Remove the extra 'leave/' prefix
    path('analytics/', leave_analytics, name='leave-analytics'),
] 