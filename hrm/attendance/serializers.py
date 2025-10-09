from rest_framework import serializers
from .models import WorkShift, OffDay, AttendanceRecord, AttendanceRule
from core.validators import validate_date_range


class WorkShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkShift
        fields = [
            "id",
            "name",
            "start_time",
            "end_time",
            "grace_minutes",
            "created_at",
            "updated_at",
        ]


class OffDaySerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        # For OffDay, ensure date is not in the past unrealistic far (optional business rule)
        return attrs
    class Meta:
        model = OffDay
        fields = ["id", "employee", "date", "reason", "created_at"]


class AttendanceRecordSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        check_in = attrs.get('check_in') or getattr(self.instance, 'check_in', None)
        check_out = attrs.get('check_out') or getattr(self.instance, 'check_out', None)
        if check_in and check_out and check_out < check_in:
            raise serializers.ValidationError({'check_out': 'check_out cannot be earlier than check_in'})
        return attrs
    class Meta:
        model = AttendanceRecord
        fields = [
            "id",
            "employee",
            "work_shift",
            "date",
            "check_in",
            "check_out",
            "biometric_id",
            "gps_latitude",
            "gps_longitude",
            "status",
            "total_seconds_worked",
            "notes",
            "created_at",
            "updated_at",
        ]


class AttendanceRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceRule
        fields = [
            "id",
            "name",
            "rule_type",
            "description",
            "is_active",
            "priority",
            "late_threshold_minutes",
            "late_penalty_type",
            "late_penalty_value",
            "overtime_threshold_hours",
            "overtime_rate_multiplier",
            "max_overtime_hours",
            "consecutive_absent_threshold",
            "monthly_absent_threshold",
            "absenteeism_action",
            "standard_work_hours",
            "min_work_hours",
            "max_work_hours",
            "break_duration_minutes",
            "break_intervals",
            "public_holidays",
            "holiday_pay_multiplier",
            "business",
            "department",
            "created_at",
            "updated_at",
        ]


