from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from .analytics.attendance_analytics import AttendanceAnalyticsService

from .models import WorkShift, OffDay, AttendanceRecord, AttendanceRule
from .serializers import (
    WorkShiftSerializer,
    OffDaySerializer,
    AttendanceRecordSerializer,
    AttendanceRuleSerializer,
)


class WorkShiftViewSet(viewsets.ModelViewSet):
    queryset = WorkShift.objects.all()
    serializer_class = WorkShiftSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]
    throttle_scope = "user"


class OffDayViewSet(viewsets.ModelViewSet):
    queryset = OffDay.objects.all()
    serializer_class = OffDaySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["employee__user__email", "reason"]
    ordering_fields = ["date", "created_at"]
    throttle_scope = "user"


class AttendanceRecordViewSet(viewsets.ModelViewSet):
    queryset = AttendanceRecord.objects.all()
    serializer_class = AttendanceRecordSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["employee__user__email", "notes"]
    ordering_fields = ["date", "created_at", "updated_at"]
    throttle_scope = "user"

    @action(detail=True, methods=["post"], url_path="check-in")
    def check_in(self, request, pk=None):
        record: AttendanceRecord = self.get_object()
        if record.check_in:
            return Response({"detail": "Already checked in."}, status=status.HTTP_400_BAD_REQUEST)
        record.check_in = timezone.now()
        record.save(update_fields=["check_in", "updated_at"])
        return Response(self.get_serializer(record).data)

    @action(detail=True, methods=["post"], url_path="check-out")
    def check_out(self, request, pk=None):
        record: AttendanceRecord = self.get_object()
        if not record.check_in:
            return Response({"detail": "Check-in required first."}, status=status.HTTP_400_BAD_REQUEST)
        if record.check_out:
            return Response({"detail": "Already checked out."}, status=status.HTTP_400_BAD_REQUEST)
        record.check_out = timezone.now()
        # compute worked seconds
        worked = int((record.check_out - record.check_in).total_seconds()) if record.check_in else 0
        record.total_seconds_worked = max(worked, 0)
        record.save(update_fields=["check_out", "total_seconds_worked", "updated_at"])
        return Response(self.get_serializer(record).data)


class AttendanceRuleViewSet(viewsets.ModelViewSet):
    queryset = AttendanceRule.objects.all()
    serializer_class = AttendanceRuleSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "rule_type", "description"]
    ordering_fields = ["priority", "name", "created_at"]
    throttle_scope = "user"


@api_view(['GET'])
def attendance_analytics(request):
    """
    Get attendance analytics data.
    """
    try:
        period = request.query_params.get('period', 'month')
        business_id = request.query_params.get('business_id')
        
        analytics_service = AttendanceAnalyticsService()
        data = analytics_service.get_attendance_dashboard_data(
            business_id=business_id,
            period=period
        )
        
        return Response({
            'success': True,
            'data': data,
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error fetching attendance analytics: {str(e)}',
            'timestamp': timezone.now().isoformat()
        }, status=500)

