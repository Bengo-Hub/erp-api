from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    WorkShiftViewSet, OffDayViewSet, AttendanceRecordViewSet, AttendanceRuleViewSet,
    ShiftRotationViewSet, TimesheetViewSet, TimesheetEntryViewSet, attendance_analytics
)
from .shift_planner_api import (
    ShiftRosterViewSet, ShiftAssignmentViewSet, StaffShiftOverrideViewSet, ShiftPlannerResolveView,
)


router = DefaultRouter()
router.register(r'work-shifts', WorkShiftViewSet, basename='work-shifts')
router.register(r'shift-rotations', ShiftRotationViewSet, basename='shift-rotations')
router.register(r'off-days', OffDayViewSet, basename='off-days')
router.register(r'records', AttendanceRecordViewSet, basename='attendance-records')
router.register(r'rules', AttendanceRuleViewSet, basename='attendance-rules')
router.register(r'timesheets', TimesheetViewSet, basename='timesheets')
router.register(r'timesheet-entries', TimesheetEntryViewSet, basename='timesheet-entries')
# Shift planner (POS-adapted): rosters + slots, assignments, per-date overrides, resolve-for-range
router.register(r'shift-rosters', ShiftRosterViewSet, basename='shift-rosters')
router.register(r'shift-assignments', ShiftAssignmentViewSet, basename='shift-assignments')
router.register(r'staff-shift-overrides', StaffShiftOverrideViewSet, basename='staff-shift-overrides')
router.register(r'shift-planner', ShiftPlannerResolveView, basename='shift-planner')

urlpatterns = [
    path('', include(router.urls)),
    path('analytics/', attendance_analytics, name='attendance-analytics'),
]


