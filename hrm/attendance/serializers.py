from rest_framework import serializers
from .models import  (WorkShift, WorkShiftSchedule, OffDay, AttendanceRecord,
 AttendanceRule, ShiftRotation, ESSSettings, Timesheet, TimesheetEntry)
from core.validators import validate_date_range


class WorkShiftScheduleSerializer(serializers.ModelSerializer):
    """Serializer for day-wise work shift schedules"""
    
    class Meta:
        model = WorkShiftSchedule
        fields = [
            "id",
            "day",
            "start_time",
            "end_time",
            "break_hours",
            "is_working_day",
        ]
        extra_kwargs = {
            'id': {'read_only': True},
        }

    def validate(self, attrs):
        """Validate that end_time is after start_time"""
        start_time = attrs.get('start_time')
        end_time = attrs.get('end_time')
        
        if start_time and end_time and end_time <= start_time:
            raise serializers.ValidationError({
                'end_time': 'End time must be after start time'
            })
        
        return attrs


class WorkShiftSerializer(serializers.ModelSerializer):
    """Serializer for work shifts with nested schedule support"""
    schedule = WorkShiftScheduleSerializer(many=True, required=False)
    active_rotation = serializers.SerializerMethodField()
    
    class Meta:
        model = WorkShift
        fields = [
            "id",
            "name",
            "start_time",
            "end_time",
            "grace_minutes",
            "total_hours_per_week",
            "schedule",
            "active_rotation",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            'start_time': {'required': False},
            'end_time': {'required': False},
        }
    
    def get_active_rotation(self, obj):
        """Get active rotation for this shift"""
        active_rotation = obj.current_rotations.filter(is_active=True).first()
        if active_rotation:
            return {
                'id': active_rotation.id,
                'title': active_rotation.title,
                'run_duration': active_rotation.run_duration,
                'run_unit': active_rotation.run_unit,
                'next_change_date': active_rotation.next_change_date
            }
        return None

    def validate(self, attrs):
        """Validate work shift data"""
        schedule = attrs.get('schedule', [])
        
        # If schedule is provided, validate it
        if schedule:
            # Ensure at least one working day is defined
            working_days = [s for s in schedule if s.get('is_working_day', True)]
            if not working_days:
                raise serializers.ValidationError({
                    'schedule': 'At least one working day must be defined'
                })
        
        return attrs

    def create(self, validated_data):
        """Create work shift with nested schedule"""
        schedule_data = validated_data.pop('schedule', [])
        
        # Create the work shift
        work_shift = WorkShift.objects.create(**validated_data)
        
        # Create schedule entries
        for schedule_item in schedule_data:
            WorkShiftSchedule.objects.create(
                work_shift=work_shift,
                **schedule_item
            )
        
        return work_shift

    def update(self, instance, validated_data):
        """Update work shift with nested schedule"""
        schedule_data = validated_data.pop('schedule', None)
        
        # Update work shift fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update schedule if provided
        if schedule_data is not None:
            # Delete existing schedule entries
            instance.schedule.all().delete()
            
            # Create new schedule entries
            for schedule_item in schedule_data:
                WorkShiftSchedule.objects.create(
                    work_shift=instance,
                    **schedule_item
                )
        
        return instance


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


class ShiftRotationSerializer(serializers.ModelSerializer):
    """Serializer for shift rotation patterns"""
    shifts_details = WorkShiftSerializer(source='shifts', many=True, read_only=True)
    current_active_shift_details = WorkShiftSerializer(source='current_active_shift', read_only=True)
    
    class Meta:
        model = ShiftRotation
        fields = [
            "id",
            "title",
            "shifts",
            "shifts_details",
            "current_active_shift",
            "current_active_shift_details",
            "last_shift",
            "run_duration",
            "run_unit",
            "break_duration",
            "break_unit",
            "next_change_date",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class ESSSettingsSerializer(serializers.ModelSerializer):
    """Serializer for ESS Settings"""
    exempt_roles_details = serializers.SerializerMethodField()
    
    class Meta:
        model = ESSSettings
        fields = [
            'id',
            'enable_shift_based_restrictions',
            'exempt_roles',
            'exempt_roles_details',
            'allow_payslip_view',
            'allow_leave_application',
            'allow_timesheet_application',
            'allow_overtime_application',
            'allow_advance_salary_application',
            'allow_losses_damage_submission',
            'allow_expense_claims_application',
            'require_password_change_on_first_login',
            'session_timeout_minutes',
            'allow_weekend_login',
            'max_failed_login_attempts',
            'account_lockout_duration_minutes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_exempt_roles_details(self, obj):
        """Get details of exempt roles/groups"""
        from django.contrib.auth.models import Group
        roles = obj.exempt_roles.all()
        return [{'id': role.id, 'name': role.name} for role in roles]


class TimesheetEntrySerializer(serializers.ModelSerializer):
    total_hours = serializers.ReadOnlyField()
    
    class Meta:
        model = TimesheetEntry
        fields = [
            'id', 'timesheet', 'date', 'project', 'task_description',
            'regular_hours', 'overtime_hours', 'break_hours', 'notes', 'total_hours'
        ]
        read_only_fields = ['id', 'total_hours']


class TimesheetSerializer(serializers.ModelSerializer):
    entries = TimesheetEntrySerializer(many=True, read_only=True)
    employee_name = serializers.SerializerMethodField()
    approver_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Timesheet
        fields = [
            'id', 'employee', 'employee_name', 'approver', 'approver_name',
            'period_start', 'period_end', 'status', 'submission_date', 
            'approval_date', 'rejection_reason', 'total_hours', 
            'total_overtime_hours', 'notes', 'entries', 'created_at', 
            'updated_at', 'is_active'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'employee_name', 'approver_name']
    
    def get_employee_name(self, obj):
        return obj.employee.user.get_full_name() if obj.employee and obj.employee.user else 'N/A'
    
    def get_approver_name(self, obj):
        return obj.approver.get_full_name() if obj.approver else 'N/A'


