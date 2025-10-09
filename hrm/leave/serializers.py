from rest_framework import serializers
from .models import LeaveCategory, LeaveEntitlement, LeaveRequest, LeaveBalance, LeaveLog, PublicHoliday
from hrm.employees.serializers import *

class LeaveCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveCategory
        fields = ['id', 'name', 'description', 'is_active', 'created_at', 'updated_at']

class LeaveEntitlementSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    category = LeaveCategorySerializer(read_only=True)
    employee_id = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        source='employee',
        write_only=True
    )
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=LeaveCategory.objects.all(),
        source='category',
        write_only=True
    )

    class Meta:
        model = LeaveEntitlement
        fields = ['id', 'employee', 'employee_id', 'category', 'category_id', 
                 'days_entitled', 'year', 'created_at', 'updated_at']

class LeaveRequestSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    category = LeaveCategorySerializer(read_only=True)
    approved_by = EmployeeSerializer(read_only=True)
    employee_id = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        source='employee',
        write_only=True
    )
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=LeaveCategory.objects.all(),
        source='category',
        write_only=True
    )
    approved_by_id = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        source='approved_by',
        write_only=True,
        required=False
    )

    class Meta:
        model = LeaveRequest
        fields = ['id', 'employee', 'employee_id', 'category', 'category_id',
                 'start_date', 'end_date', 'days_requested', 'reason',
                 'status', 'approved_by', 'approved_by_id', 'approved_at',
                 'rejection_reason', 'created_at', 'updated_at']
        read_only_fields = ['status', 'approved_at']
        

class LeaveBalanceSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    category = LeaveCategorySerializer(read_only=True)
    employee_id = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        source='employee',
        write_only=True
    )
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=LeaveCategory.objects.all(),
        source='category',
        write_only=True
    )

    class Meta:
        model = LeaveBalance
        fields = ['id', 'employee', 'employee_id', 'category', 'category_id',
                 'year', 'days_entitled', 'days_taken', 'days_remaining',
                 'created_at', 'updated_at']

class LeaveLogSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    employee = serializers.SerializerMethodField()
    leave_type = serializers.SerializerMethodField()
    days = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = LeaveLog
        fields = ['id', 'leave_request', 'action', 'description', 'user', 
                 'created_at', 'employee', 'leave_type', 'days', 'balance']

    def get_user(self, obj):
        return obj.user.get_full_name() if obj.user else None

    def get_employee(self, obj):
        return f"{obj.leave_request.employee.user.first_name} {obj.leave_request.employee.user.last_name}"

    def get_leave_type(self, obj):
        return obj.leave_request.category.name

    def get_days(self, obj):
        return obj.leave_request.days_requested

    def get_balance(self, obj):
        balance = LeaveBalance.objects.filter(
            employee=obj.leave_request.employee,
            category=obj.leave_request.category,
            year=obj.leave_request.start_date.year
        ).first()
        return balance.days_remaining if balance else 0 


class PublicHolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = PublicHoliday
        fields = ['id', 'name', 'date', 'is_national', 'county', 'created_at', 'updated_at']