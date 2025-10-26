from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    WorkShiftViewSet, OffDayViewSet, AttendanceRecordViewSet, AttendanceRuleViewSet, 
    ShiftRotationViewSet, TimesheetViewSet, TimesheetEntryViewSet, attendance_analytics
)


router = DefaultRouter()
router.register(r'work-shifts', WorkShiftViewSet, basename='work-shifts')
router.register(r'shift-rotations', ShiftRotationViewSet, basename='shift-rotations')
router.register(r'off-days', OffDayViewSet, basename='off-days')
router.register(r'records', AttendanceRecordViewSet, basename='attendance-records')
router.register(r'rules', AttendanceRuleViewSet, basename='attendance-rules')
router.register(r'timesheets', TimesheetViewSet, basename='timesheets')
router.register(r'timesheet-entries', TimesheetEntryViewSet, basename='timesheet-entries')

urlpatterns = [
    path('', include(router.urls)),
    path('analytics/', attendance_analytics, name='attendance-analytics'),
]


