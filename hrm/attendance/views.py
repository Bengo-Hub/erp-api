from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.utils import timezone
from .analytics.attendance_analytics import AttendanceAnalyticsService
from hrm.employees.permissions import StaffDataFilterMixin, SensitiveModuleFilterMixin

from .models import WorkShift, WorkShiftSchedule, ShiftRotation, OffDay, AttendanceRecord, AttendanceRule, Timesheet, TimesheetEntry
from .serializers import (
    WorkShiftSerializer,
    WorkShiftScheduleSerializer,
    OffDaySerializer,
    AttendanceRecordSerializer,
    AttendanceRuleSerializer,
    ShiftRotationSerializer,
    TimesheetSerializer,
    TimesheetEntrySerializer,
)
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class WorkShiftViewSet(BaseModelViewSet):
    queryset = WorkShift.objects.all()
    serializer_class = WorkShiftSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]
    throttle_scope = "user"


class OffDayViewSet(BaseModelViewSet):
    queryset = OffDay.objects.all().select_related('employee')
    serializer_class = OffDaySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["employee__user__email", "reason"]
    ordering_fields = ["date", "created_at"]
    
    def get_queryset(self):
        from hrm.utils.filter_utils import get_filter_params, apply_hrm_filters
        
        queryset = super().get_queryset()
        
        # Get standardized filter parameters
        filter_params = get_filter_params(self.request)
        
        # Apply HRM filters (branch, department, region, project, employee)
        queryset = apply_hrm_filters(queryset, filter_params, filter_prefix='employee__hr_details')
        
        return queryset


class AttendanceRecordViewSet(BaseModelViewSet):
    queryset = AttendanceRecord.objects.all().select_related('employee', 'shift')
    serializer_class = AttendanceRecordSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["employee__user__email", "notes"]
    ordering_fields = ["date", "created_at", "updated_at"]
    throttle_scope = "user"
    
    def get_queryset(self):
        from hrm.utils.filter_utils import get_filter_params, apply_hrm_filters
        
        queryset = super().get_queryset()
        
        # Get standardized filter parameters
        filter_params = get_filter_params(self.request)
        
        # Apply HRM filters (branch, department, region, project, employee)
        queryset = apply_hrm_filters(queryset, filter_params, filter_prefix='employee__hr_details')
        
        return queryset

    @action(detail=True, methods=["post"], url_path="check-in")
    def check_in(self, request, pk=None):
        """Check in for attendance record."""
        try:
            correlation_id = get_correlation_id(request)
            record: AttendanceRecord = self.get_object()
            
            if record.check_in:
                return APIResponse.bad_request(
                    message='Already checked in',
                    error_id='already_checked_in',
                    correlation_id=correlation_id
                )
            
            record.check_in = timezone.now()
            record.save(update_fields=["check_in", "updated_at"])
            
            # Log the check-in
            AuditTrail.log(
                operation=AuditTrail.UPDATE,
                module='hrm',
                entity_type='AttendanceRecord',
                entity_id=record.id,
                user=request.user,
                changes={'check_in': {'new': record.check_in}},
                reason='Employee checked in',
                request=request
            )
            
            return APIResponse.success(
                data=self.get_serializer(record).data,
                message='Check-in recorded successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error during check-in: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error recording check-in',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=["post"], url_path="check-out")
    def check_out(self, request, pk=None):
        """Check out for attendance record."""
        try:
            correlation_id = get_correlation_id(request)
            record: AttendanceRecord = self.get_object()
            
            if not record.check_in:
                return APIResponse.bad_request(
                    message='Check-in required first',
                    error_id='no_check_in',
                    correlation_id=correlation_id
                )
            
            if record.check_out:
                return APIResponse.bad_request(
                    message='Already checked out',
                    error_id='already_checked_out',
                    correlation_id=correlation_id
                )
            
            record.check_out = timezone.now()
            # compute worked seconds
            worked = int((record.check_out - record.check_in).total_seconds()) if record.check_in else 0
            record.total_seconds_worked = max(worked, 0)
            record.save(update_fields=["check_out", "total_seconds_worked", "updated_at"])
            
            # Log the check-out
            AuditTrail.log(
                operation=AuditTrail.UPDATE,
                module='hrm',
                entity_type='AttendanceRecord',
                entity_id=record.id,
                user=request.user,
                changes={'check_out': {'new': record.check_out}, 'total_seconds_worked': {'new': record.total_seconds_worked}},
                reason='Employee checked out',
                request=request
            )
            
            return APIResponse.success(
                data=self.get_serializer(record).data,
                message='Check-out recorded successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error during check-out: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error recording check-out',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )


class AttendanceRuleViewSet(BaseModelViewSet):
    queryset = AttendanceRule.objects.all()
    serializer_class = AttendanceRuleSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "rule_type", "description"]
    ordering_fields = ["priority", "name", "created_at"]
    throttle_scope = "user"


class ShiftRotationViewSet(BaseModelViewSet):
    """
    ViewSet for managing shift rotations.
    """
    queryset = ShiftRotation.objects.all()
    serializer_class = ShiftRotationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title"]
    ordering_fields = ["title", "created_at"]
    throttle_scope = "user"


@api_view(['GET'])
def attendance_analytics(request):
    """
    Get attendance analytics data with standardized response format.
    """
    try:
        correlation_id = get_correlation_id(request)
        period = request.query_params.get('period', 'month')
        business_id = request.query_params.get('business_id')
        
        # Validate period
        valid_periods = ['week', 'month', 'quarter', 'year']
        if period not in valid_periods:
            return APIResponse.validation_error(
                message='Invalid period parameter',
                errors={'period': f'Must be one of: {", ".join(valid_periods)}'},
                correlation_id=correlation_id
            )
        
        analytics_service = AttendanceAnalyticsService()
        data = analytics_service.get_attendance_dashboard_data(
            business_id=business_id,
            period=period
        )
        
        # Log analytics access
        AuditTrail.log(
            operation=AuditTrail.EXPORT,
            module='hrm',
            entity_type='AttendanceAnalytics',
            entity_id=business_id or 'all',
            user=request.user,
            reason=f'Attendance analytics export for period: {period}',
            request=request
        )
        
        return APIResponse.success(
            data=data,
            message='Attendance analytics retrieved successfully',
            correlation_id=correlation_id
        )
    except Exception as e:
        logger.error(f'Error fetching attendance analytics: {str(e)}', exc_info=True)
        correlation_id = get_correlation_id(request)
        return APIResponse.server_error(
            message='Error fetching attendance analytics',
            error_id=str(e),
            correlation_id=correlation_id
        )


class TimesheetViewSet(SensitiveModuleFilterMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing employee timesheets
    """
    queryset = Timesheet.objects.filter(is_active=True)
    serializer_class = TimesheetSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employee', 'status', 'period_start', 'period_end']
    search_fields = ['employee__user__first_name', 'employee__user__last_name']
    ordering_fields = ['period_start', 'created_at', 'status']
    ordering = ['-period_start']
    
    def get_queryset(self):
        """Filter timesheets based on user role"""
        user = self.request.user
        qs = super().get_queryset()
        
        # If user is an employee, only show their own timesheets
        if hasattr(user, 'employee'):
            return qs.filter(employee=user.employee)
        
        # Admins and managers can see all timesheets
        return qs
    
    @action(detail=True, methods=['post'], url_path='submit')
    def submit_timesheet(self, request, pk=None):
        """Submit timesheet for approval"""
        timesheet = self.get_object()
        
        if timesheet.status != 'draft':
            return Response(
                {'error': 'Only draft timesheets can be submitted'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        timesheet.status = 'submitted'
        timesheet.submission_date = timezone.now()
        timesheet.save()
        
        return Response(
            {'message': 'Timesheet submitted for approval'},
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=['post'], url_path='approve')
    def approve_timesheet(self, request, pk=None):
        """Approve timesheet"""
        timesheet = self.get_object()
        
        if timesheet.status != 'submitted':
            return Response(
                {'error': 'Only submitted timesheets can be approved'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        timesheet.status = 'approved'
        timesheet.approval_date = timezone.now()
        timesheet.approver = request.user
        timesheet.save()
        
        return Response(
            {'message': 'Timesheet approved successfully'},
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=['post'], url_path='reject')
    def reject_timesheet(self, request, pk=None):
        """Reject timesheet"""
        timesheet = self.get_object()
        
        if timesheet.status != 'submitted':
            return Response(
                {'error': 'Only submitted timesheets can be rejected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        timesheet.status = 'rejected'
        timesheet.rejection_reason = request.data.get('reason', '')
        timesheet.approver = request.user
        timesheet.save()
        
        return Response(
            {'message': 'Timesheet rejected'},
            status=status.HTTP_200_OK
        )


class TimesheetEntryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing timesheet entries
    """
    queryset = TimesheetEntry.objects.all()
    serializer_class = TimesheetEntrySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['timesheet', 'date', 'project']
    ordering_fields = ['date']
    ordering = ['date']

