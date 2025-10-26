from rest_framework import serializers
from hrm.employees.models import HRDetails
from hrm.payroll_settings.models import *
from django.contrib.auth import get_user_model

User=get_user_model()

class ScheduledPayslipSerializer(serializers.ModelSerializer):
    composer = serializers.SerializerMethodField()
    recipients = serializers.SerializerMethodField()
    
    class Meta:
        model = ScheduledPayslip
        fields = '__all__'

    def get_composer(self, obj):
        if obj.composer is not None:
            return {"name": f'{obj.composer.first_name} {obj.composer.last_name}', "id": obj.composer.id}
        return None
    
    def get_recipients(self, obj):
        recipients = obj.recipients
        resps = []
        for employee in recipients:
            try:
                hr_details = HRDetails.objects.get(employee=employee)
                resps.append({
                    'id': employee.id,
                    'staffNo': hr_details.job_or_staff_number,
                    'name': f"{employee.user.first_name} {employee.user.middle_name} {employee.user.last_name}",
                    'email': employee.user.email,
                })
            except HRDetails.DoesNotExist:
                # Fallback if HR details don't exist
                resps.append({
                    'id': employee.id,
                    'staffNo': 'N/A',
                    'name': f"{employee.user.first_name} {employee.user.middle_name} {employee.user.last_name}",
                    'email': employee.user.email,
                })
        return resps


class ApprovalSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    class Meta:
        model = Approval
        fields = '__all__'

    def get_user(self, obj):
        return {"name": f'{obj.user.first_name} {obj.user.last_name}', "id": obj.user.id, "email": obj.user.email}
    def get_content_type(self, obj):
        return {"name": obj.content_type.name, "id": obj.content_type.id, "model": obj.content_type.model, "app_label": obj.content_type.app_label}

class FormulaItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormulaItems
        fields = [
            'id', 'formula', 'amount_from', 'amount_to', 
            'deduct_amount', 'deduct_percentage'
        ]
        read_only_fields = ['id']

class SplitRatioSerializer(serializers.ModelSerializer):
    class Meta:
        model = SplitRatio
        fields = [
            'id', 'formula', 'employee_percentage', 'employer_percentage'
        ]
        read_only_fields = ['id']

class FormulasSerializer(serializers.ModelSerializer):
    class Meta:
        model = Formulas
        fields = [
            'id', 'type', 'deduction', 'category', 'title', 'unit',
            'effective_from', 'effective_to', 'upper_limit', 'upper_limit_amount',
            'upper_limit_percentage', 'personal_relief', 'relief_carry_forward',
            'min_taxable_income', 'progressive', 'created_at', 'is_current',
            'version', 'transition_date', 'replaces_formula', 'regulatory_source',
            'notes', 'deduction_order'
        ]
        read_only_fields = ['id', 'created_at']

class PayrollComponentsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollComponents
        fields = [
            'id', 'title', 'wb_code', 'non_cash', 'deduct_after_taxing',
            'checkoff', 'statutory', 'constant', 'mode', 'is_active'
        ]


class LoansSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loans
        fields = '__all__'


class GeneralHRSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneralHRSettings
        fields = ['id', 'overtime_normal_days', 'overtime_non_working_days', 'overtime_holidays',
                  'partial_months', 'round_off_currency', 'round_off_amount', 'allow_backwards_payroll',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']