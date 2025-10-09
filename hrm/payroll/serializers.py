from django.db import IntegrityError
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework import status
from pytz import timezone as pytz_timezone

from hrm.employees.serializers import EmployeeSerializer
from .models import *
from hrm.employees.models import *
from django.contrib.auth import get_user_model

User=get_user_model()

class PayrollComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollComponents
        fields = [
            'id', 'title', 'wb_code', 'non_cash', 'deduct_after_taxing', 'checkoff',
            'statutory', 'constant', 'mode', 'is_active'
        ] 

class DeductionSerializer(serializers.ModelSerializer):
    deduction = PayrollComponentSerializer()

    class Meta:
        model = Deductions
        fields = ['deduction', 'quantity','amount']

class BenefitSerializer(serializers.ModelSerializer):
    benefit = PayrollComponentSerializer()

    class Meta:
        model = Benefits
        fields = ['benefit', 'amount']

class EarningSerializer(serializers.ModelSerializer):
    earning = PayrollComponentSerializer()

    class Meta:
        model = Earnings
        fields = ['earning', 'quantity', 'amount']

class ExpenseClaimsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseClaims
        fields = ['approver', 'approved', 'category','application_date','attachment']

class LoanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loans
        fields = ['title',]

class EmployeeLoanSerializer(serializers.ModelSerializer):
    loan=LoanSerializer()
    class Meta:
        model = EmployeLoans
        fields = ['loan', 'monthly_installment','no_of_installments_paid','interest_paid']

class RepaymentOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RepayOption
        fields = ['amount','no_of_installments','installment_amount']

class EmployeeAdvancesSerializer(serializers.ModelSerializer):
    repay_option = RepaymentOptionSerializer()
    employee_id = serializers.IntegerField(write_only=True, required=True)
    approver = serializers.SerializerMethodField()
    employee = serializers.SerializerMethodField()
    
    class Meta:
        model = Advances
        fields = ['id', 'employee_id', 'employee', 'approver', 'approved', 
                 'issue_date', 'repay_option', 'next_payment_date', 'amount_repaid']
        extra_kwargs = {
            'employee_id': {'required': True},
            'repay_option': {'required': True},
            'next_payment_date': {'required': True}
        }

    def get_approver(self, obj):
        if obj.approver is not None:
            return {
                "name": f'{obj.approver.first_name} {obj.approver.last_name}',
                "email": obj.approver.email,
                "id": obj.approver.id
            }
        return None
    
    def get_employee(self, obj):
        employee = obj.employee
        if not employee:
            return None
            
        try:
            hr_details = HRDetails.objects.get(employee=employee)
            staff_no = hr_details.job_or_staff_number
        except HRDetails.DoesNotExist:
            staff_no = None
            
        first_name = employee.user.first_name or ""
        middle_name = employee.user.middle_name or ""
        last_name = employee.user.last_name or ""
        
        return {
            'id': employee.id,
            'staffNo': staff_no,
            'name': f"{first_name} {middle_name} {last_name}".strip(),
        }

    def validate(self, data):
        # Validate employee exists
        employee_id = data.get('employee_id')
        if not employee_id:
            raise serializers.ValidationError({"employee_id": "This field is required."})
        
        try:
            employee = Employee.objects.get(pk=employee_id)
            data['employee'] = employee
        except Employee.DoesNotExist:
            raise serializers.ValidationError({"employee_id": "Invalid employee ID"})
        
        # Validate repay_option data
        repay_option_data = data.get('repay_option', {})
        if not repay_option_data:
            raise serializers.ValidationError({"repay_option": "This field is required."})
            
        return data
    
    def create(self, validated_data):
        repay_option_data = validated_data.pop('repay_option')
        
        try:
            # Create or get existing repay option
            repay_option, _ = RepayOption.objects.get_or_create(
                **repay_option_data
            )
            
            # Create advance with the repay option
            advance = Advances.objects.create(
                **validated_data,
                repay_option=repay_option
            )
            return advance
            
        except IntegrityError as e:
            raise serializers.ValidationError(
                {"database_error": "Failed to create advance record. Please check all required fields."}
            )
    
    def update(self, instance, validated_data):
        repay_option_data = validated_data.pop('repay_option', None)
        
        # Update advance fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Update repay option if provided
        if repay_option_data:
            repay_option, _ = RepayOption.objects.get_or_create(
                **repay_option_data
            )
            instance.repay_option = repay_option
        
        instance.save()
        return instance
        
class EmployeeLossDamagesSerializer(serializers.ModelSerializer):
    repay_option = RepaymentOptionSerializer()
    employee_id = serializers.IntegerField(write_only=True, required=True)
    approver = serializers.SerializerMethodField()
    employee = serializers.SerializerMethodField()
    class Meta:
        model = LossesAndDamages
        fields = ['id', 'description', 'employee_id', 'employee', 'approver', 'approved', 
                 'issue_date', 'repay_option', 'next_payment_date', 'amount_repaid']
        extra_kwargs = {
            'employee_id': {'required': True},
            'repay_option': {'required': True},
            'next_payment_date': {'required': True}
        }

    def get_approver(self, obj):
        if obj.approver is not None:
            return {
                "name": f'{obj.approver.first_name} {obj.approver.last_name}',
                "email": obj.approver.email,
                "id": obj.approver.id
            }
        return None
    
    def get_employee(self, obj):
        employee = obj.employee
        if not employee:
            return None
            
        try:
            hr_details = HRDetails.objects.get(employee=employee)
            staff_no = hr_details.job_or_staff_number
        except HRDetails.DoesNotExist:
            staff_no = None
            
        first_name = employee.user.first_name or ""
        middle_name = employee.user.middle_name or ""
        last_name = employee.user.last_name or ""
        
        return {
            'id': employee.id,
            'staffNo': staff_no,
            'name': f"{first_name} {middle_name} {last_name}".strip(),
        }

    def validate(self, data):
        # Validate employee exists
        employee_id = data.get('employee_id')
        if not employee_id:
            raise serializers.ValidationError({"employee_id": "This field is required."})
        
        try:
            employee = Employee.objects.get(pk=employee_id)
            data['employee'] = employee
        except Employee.DoesNotExist:
            raise serializers.ValidationError({"employee_id": "Invalid employee ID"})
        
        # Validate repay_option data
        repay_option_data = data.get('repay_option', {})
        if not repay_option_data:
            raise serializers.ValidationError({"repay_option": "This field is required."})
            
        return data
    
    def create(self, validated_data):
        repay_option_data = validated_data.pop('repay_option')
        
        try:
            # Create or get existing repay option
            repay_option, _ = RepayOption.objects.get_or_create(
                **repay_option_data
            )
            
            # Create advance with the repay option
            advance = Advances.objects.create(
                **validated_data,
                repay_option=repay_option
            )
            return advance
            
        except IntegrityError as e:
            raise serializers.ValidationError(
                {"database_error": "Failed to create advance record. Please check all required fields."}
            )
    
    def update(self, instance, validated_data):
        repay_option_data = validated_data.pop('repay_option', None)
        
        # Update advance fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Update repay option if provided
        if repay_option_data:
            repay_option, _ = RepayOption.objects.get_or_create(
                **repay_option_data
            )
            instance.repay_option = repay_option
        
        instance.save()
        return instance
    
class ClaimItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClaimItems
        fields = '__all__'

class ExpenseClaimSerializer(serializers.ModelSerializer):
    employee=serializers.SerializerMethodField()
    approver=serializers.SerializerMethodField()
    claim_items = ClaimItemSerializer(source="expense_categories", many=True, required=False)
    class Meta:
        model = ExpenseClaims
        fields = '__all__'
        #depth=1

    def get_employee(self,obj):
        if obj.employee is not None:
            employee=obj.employee
            staffNo=HRDetails.objects.get(employee=employee).job_or_staff_number
            return {'id':employee.id,'staffNo':staffNo,'name':f'{employee.user.first_name} {employee.user.last_name}'}
        
    def get_approver(self,obj):
        if obj.approver is not None:
            approver=obj.approver
            return {'id':approver.id,'email':approver.email,'name':f'{approver.first_name} {approver.last_name}'}  

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'first_name','middle_name','last_name', 'email')

class PayslipSerializer(serializers.ModelSerializer):
    employee = serializers.SerializerMethodField()
    deductions = serializers.SerializerMethodField()
    benefits = serializers.SerializerMethodField()
    earnings = serializers.SerializerMethodField()
    loans = serializers.SerializerMethodField()
    advances = serializers.SerializerMethodField()
    loss_damages=serializers.SerializerMethodField()
    claims = serializers.SerializerMethodField()
    created_by=serializers.SerializerMethodField()
    approver=serializers.SerializerMethodField()

    class Meta:
        model = Payslip
        fields = [
            'id', 'employee', 'created_by', 'gross_pay', 'total_earnings', 'net_pay',
            'taxable_pay', 'paye', 'tax_relief', 'reliefs', 'gross_pay_after_tax',
            'shif_or_nhif_contribution', 'housing_levy', 'nssf_employee_tier_1', 'nssf_employee_tier_2',
            'nssf_employer_contribution', 'deductions_before_tax', 'deductions_after_tax',
            'deductions_after_paye', 'deductions_final', 'payment_period', 'payroll_status',
            'approval_status', 'approver', 'published', 'payroll_date', 'period_start',
            'period_end', 'kra_paye_reference', 'kra_filed_at', 'delete_status',
            'deductions', 'benefits', 'earnings', 'loans', 'advances', 'loss_damages', 'claims'
        ]
        depth = 1

    def get_approver(self,obj):
        if obj.approver is not None:
           return {"name":f'{obj.approver.first_name} {obj.approver.last_name}',"email":obj.approver.email,"id":obj.approver.id}
        return None
    
    def get_created_by(self,obj):
        if obj.created_by is not None:
           return {"name":f'{obj.created_by.first_name} {obj.created_by.last_name}',"email":obj.created_by.email,"id":obj.created_by.id}
        return None
    
    def get_employee(self, obj):
        employee = obj.employee
        hr_details = HRDetails.objects.get(employee=employee)
        salary_details = SalaryDetails.objects.get(employee=employee)
        return {
            'id': employee.id,
            'staffNo': hr_details.job_or_staff_number,
            'job_title': hr_details.job_title.title,
            'region': hr_details.region.name,
            'department': hr_details.department.title,
            'name': f"{employee.user.first_name} {employee.user.middle_name} {employee.user.last_name}",
            'email': employee.user.email,
            'personal_email': employee.contacts.first().personal_email,
            'pin': employee.pin_no,
            'id_no': employee.national_id,
            'basic_salary': salary_details.monthly_salary,
            'payment_type': salary_details.get_payment_type_display(),
            'bank': {
                'name': salary_details.bank_account.bank_institution.name if salary_details.bank_account else 'N/A',
                'acc': salary_details.bank_account.account_number if salary_details.bank_account else 'N/A'
            }
        }

    def get_deductions(self, obj):
        """Get calculated deduction amounts for the payslip"""
        deductions = []
        
        # Get NSSF deductions
        if obj.nssf_employee_tier_1 > 0 or obj.nssf_employee_tier_2 > 0:
            deductions.append({
                'deduction': {
                    'id': 1,
                    'title': 'N.S.S.F',
                    'wb_code': 'C24167',
                    'non_cash': False,
                    'deduct_after_taxing': False,
                    'checkoff': True,
                    'statutory': True,
                    'constant': True,
                    'mode': 'monthly',
                    'is_active': True
                },
                'quantity': '0.0000',
                'amount': str(obj.nssf_employee_tier_1 + obj.nssf_employee_tier_2)
            })
        
        # Get SHIF/NHIF deductions
        if obj.shif_or_nhif_contribution > 0:
            # Determine if it's SHIF or NHIF based on payment period (2025+ uses SHIF)
            is_shif = obj.payment_period and obj.payment_period.year >= 2025
            title = 'S.H.I.F' if is_shif else 'N.H.I.F'
            
            deductions.append({
                'deduction': {
                    'id': 2,
                    'title': title,
                    'wb_code': 'C47208',
                    'non_cash': False,
                    'deduct_after_taxing': False,
                    'checkoff': True,
                    'statutory': True,
                    'constant': True,
                    'mode': 'monthly',
                    'is_active': True
                },
                'quantity': '0.0000',
                'amount': str(obj.shif_or_nhif_contribution)
            })
        
        # Get Housing Levy
        if obj.housing_levy > 0:
            deductions.append({
                'deduction': {
                    'id': 5,
                    'title': 'Housing Levy',
                    'wb_code': 'C93647',
                    'non_cash': False,
                    'deduct_after_taxing': False,
                    'checkoff': True,
                    'statutory': True,
                    'constant': True,
                    'mode': 'monthly',
                    'is_active': True
                },
                'quantity': '0.0000',
                'amount': str(obj.housing_levy)
            })
        
        return deductions

    def get_earnings(self, obj):
        # Filter earnings based on end_date and payment mode
        return EarningSerializer(
            obj.employee.earnings.filter(
                models.Q(end_date=obj.payroll_date) | 
                models.Q(earning__mode='monthly')  # Adjust 'mode' field as per your model
            ),
            many=True
        ).data
    
    def get_benefits(self, obj):
        # Filter earnings based on end_date and payment mode
        return BenefitSerializer(
            obj.employee.benefits.filter(
                models.Q(end_date=obj.payroll_date) | 
                models.Q(benefit__mode='monthly')  # Adjust 'mode' field as per your model
            ),
            many=True
        ).data

    def get_loans(self, obj):
        # Filter loans based on end_date
        return EmployeeLoanSerializer(
            obj.employee.employeeloans.filter(
                end_date__gte=obj.payroll_date
            ),
            many=True
        ).data

    def get_advances(self, obj):
        # Filter advances based on prev_payment_date
        return EmployeeAdvancesSerializer(
            obj.employee.advances.filter(
                prev_payment_date=obj.payroll_date
            ),
            many=True
        ).data
    
    def get_loss_damages(self, obj):
        # Filter advances based on prev_payment_date
        return EmployeeLossDamagesSerializer(
            obj.employee.loss_damages.filter(
                prev_payment_date=obj.payroll_date
            ),
            many=True
        ).data

    def get_claims(self, obj):
        # Filter claims based on payment_date
        return ExpenseClaimsSerializer(
            obj.employee.expense_claims.filter(
                payment_date=obj.payroll_date,
                schedule_to_payroll=True
            ),
            many=True
        ).data

class PayrollEmployeeSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    staffNo = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    region = serializers.SerializerMethodField()
    project = serializers.SerializerMethodField()
    employment_type = serializers.SerializerMethodField()
    basic_salary = serializers.SerializerMethodField()
    benefits = serializers.SerializerMethodField()
    deductions = serializers.SerializerMethodField()
    advances = serializers.SerializerMethodField()
    earnings = serializers.SerializerMethodField()
    loans = serializers.SerializerMethodField()
    
    class Meta:
        model = Employee
        fields = ['id', 'name', 'staffNo', 'department', 'region', 'project', 'employment_type', 'basic_salary', 'benefits', 'deductions', 'advances', 'earnings', 'loans']
    
    def get_name(self, obj):
        try:
            hr_details = HRDetails.objects.get(employee=obj)
            return f"{obj.user.first_name} {obj.user.middle_name} {obj.user.last_name}[{hr_details.job_or_staff_number}]"
        except HRDetails.DoesNotExist:
            return f"{obj.user.first_name} {obj.user.middle_name} {obj.user.last_name}[N/A]"
    
    def get_staffNo(self, obj):
        try:
            hr_details = HRDetails.objects.get(employee=obj)
            return hr_details.job_or_staff_number
        except HRDetails.DoesNotExist:
            return None
    
    def get_department(self, obj):
        try:
            hr_details = HRDetails.objects.get(employee=obj)
            if hr_details.department:
                return {
                    'id': hr_details.department.id,
                    'title': hr_details.department.title
                }
        except HRDetails.DoesNotExist:
            pass
        return None
    
    def get_region(self, obj):
        try:
            hr_details = HRDetails.objects.get(employee=obj)
            if hr_details.region:
                return {
                    'id': hr_details.region.id,
                    'name': hr_details.region.name
                }
        except HRDetails.DoesNotExist:
            pass
        return None
    
    def get_project(self, obj):
        try:
            hr_details = HRDetails.objects.get(employee=obj)
            if hr_details.project:
                return {
                    'id': hr_details.project.id,
                    'name': hr_details.project.name
                }
        except HRDetails.DoesNotExist:
            pass
        return None
    
    def get_employment_type(self, obj):
        try:
            salary_details = SalaryDetails.objects.get(employee=obj)
            return salary_details.employment_type
        except SalaryDetails.DoesNotExist:
            return None
    
    def get_basic_salary(self, obj):
        try:
            salary_details = SalaryDetails.objects.get(employee=obj)
            return salary_details.monthly_salary
        except SalaryDetails.DoesNotExist:
            return 0
    
    def get_benefits(self, obj):
        try:
            # Get all active benefits for the employee (minimal fields)
            benefits = Benefits.objects.filter(
                employee=obj,
                is_active=True
            )
            return [{
                'id': benefit.id,
                'benefit': {
                    'id': benefit.benefit.id,
                    'title': benefit.benefit.title
                },
                'amount': benefit.amount
            } for benefit in benefits]
        except Exception:
            return []
    
    def get_deductions(self, obj):
        try:
            # Get all active deductions for the employee (minimal fields)
            deductions = Deductions.objects.filter(
                employee=obj,
                is_active=True
            )
            return [{
                'id': deduction.id,
                'deduction': {
                    'id': deduction.deduction.id,
                    'title': deduction.deduction.title
                },
                'quantity': deduction.quantity,
                'amount': deduction.amount
            } for deduction in deductions]
        except Exception:
            return []
    
    def get_advances(self, obj):
        try:
            # Get all active advances for the employee (minimal fields)
            advances = Advances.objects.filter(
                employee=obj,
                is_active=True
            )
            return [{
                'id': advance.id,
                'employee_id': advance.employee.id,
                'approved': advance.approved,
                'issue_date': advance.issue_date,
                'next_payment_date': advance.next_payment_date,
                'amount_repaid': advance.amount_repaid,
                'repay_option': {
                    'amount': advance.repay_option.amount,
                    'no_of_installments': advance.repay_option.no_of_installments,
                    'installment_amount': advance.repay_option.installment_amount
                } if advance.repay_option else None
            } for advance in advances]
        except Exception:
            return []
    
    def get_earnings(self, obj):
        try:
            # Get all active earnings for the employee (minimal fields)
            earnings = Earnings.objects.filter(
                employee=obj,
                is_active=True
            )
            return [{
                'id': earning.id,
                'earning': {
                    'id': earning.earning.id,
                    'title': earning.earning.title
                },
                'quantity': earning.quantity,
                'amount': earning.amount
            } for earning in earnings]
        except Exception:
            return []
    
    def get_loans(self, obj):
        try:
            # Get all active loans for the employee (minimal fields)
            loans = EmployeLoans.objects.filter(
                employee=obj,
                is_active=True
            )
            return [{
                'id': loan.id,
                'loan': {
                    'id': loan.loan.id,
                    'title': loan.loan.title
                },
                'monthly_installment': loan.monthly_installment,
                'no_of_installments_paid': loan.no_of_installments_paid,
                'interest_paid': loan.interest_paid
            } for loan in loans]
        except Exception:
            return []

class PayslipAuditSerializer(serializers.ModelSerializer):
    action_by = serializers.SerializerMethodField()

    class Meta:
        model = PayslipAudit  # Corrected to the PayslipAudit model
        fields = ['id', 'action', 'action_by', 'action_date', 'remarks']

    def get_action_by(self, obj):
        # Ensure the related CustomUser object exists and is serialized correctly
        if obj.action_by:
            hr_details = HRDetails.objects.filter(employee__user=obj.action_by).first()  # Handle possible missing HRDetails
            return {
                "name": f"{obj.action_by.first_name} {obj.action_by.last_name}",
                "staffNo": hr_details.job_or_staff_number if hr_details else None
            }
        return None