from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import WorkShiftViewSet, OffDayViewSet, AttendanceRecordViewSet, AttendanceRuleViewSet, attendance_analytics


router = DefaultRouter()
router.register(r'work-shifts', WorkShiftViewSet, basename='work-shifts')
router.register(r'off-days', OffDayViewSet, basename='off-days')
router.register(r'records', AttendanceRecordViewSet, basename='attendance-records')
router.register(r'rules', AttendanceRuleViewSet, basename='attendance-rules')

urlpatterns = [
    path('', include(router.urls)),
    path('analytics/', attendance_analytics, name='attendance-analytics'),
]


