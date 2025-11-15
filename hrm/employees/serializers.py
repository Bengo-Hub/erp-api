from rest_framework import serializers

from hrm.payroll.functions import *
from .models import *
from hrm.payroll.models import *

from django.contrib.auth import get_user_model

User=get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'first_name','middle_name','last_name', 'email')

# Employee Bank Account Serializer
class EmployeeBankAccountSerializer(serializers.ModelSerializer):
    bank_institution_name = serializers.CharField(source='bank_institution.name', read_only=True)
    bank_branch_name = serializers.CharField(source='bank_branch.name', read_only=True)
    
    class Meta:
        model = EmployeeBankAccount
        fields = [
            'id', 'employee', 'bank_institution', 'bank_branch', 'bank_institution_name', 'bank_branch_name',
            'account_name', 'account_number', 'account_type',
            'is_primary', 'status', 'is_verified', 'opened_date', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

# Salary Details Serializer
class SalaryDetailsSerializer(serializers.ModelSerializer):
    bank_account_details = EmployeeBankAccountSerializer(source='bank_account', read_only=True)
    work_shift_details = serializers.SerializerMethodField()
    
    class Meta:
        model = SalaryDetails
        fields = [
            'id', 'employee', 'employment_type', 'payment_currency', 'monthly_salary',
            'pay_type', 'work_hours', 'work_shift', 'work_shift_details', 'hourly_rate', 'daily_rate', 'income_tax',
            'deduct_shif_or_nhif', 'deduct_nssf', 'tax_excemption_amount',
            'excemption_cert_no', 'payment_type', 'bank_account', 'bank_account_details', 'mobile_number'
        ]
    
    def get_work_shift_details(self, obj):
        """Return work shift details including schedule"""
        if obj.work_shift:
            from hrm.attendance.serializers import WorkShiftSerializer
            return WorkShiftSerializer(obj.work_shift).data
        return None

class BenefitsSerializer(serializers.ModelSerializer):
    employee = serializers.SerializerMethodField()
    benefit=serializers.SerializerMethodField()
    percent_of_basic=serializers.SerializerMethodField()
    class Meta:
        model = Benefits
        fields = [
            'id', 'employee', 'benefit', 'amount', 'percent_of_basic',
            'start_date', 'end_date', 'is_active'
        ]

    def get_percent_of_basic(self,obj):
        return 0
    
    def get_employee(self,obj):
        employee = obj.employee
        hr_details = HRDetails.objects.get(employee=employee)
        return {
            'name': f'{employee.user.first_name} {employee.user.last_name}',
            'staffNo': hr_details.job_or_staff_number,
            'id': employee.id,
        }
    
    def get_benefit(self,obj):
        benefit = obj  # This is the deductions instance
        if benefit:
            return {
                "wb_code":benefit.benefit.wb_code,
                "title":benefit.benefit.title,
                "checkoff":benefit.benefit.checkoff,
                "taxable_status":benefit.benefit.taxable_status,
                "mode":benefit.benefit.mode,
            }
        return None 

class DeductionsSerializer(serializers.ModelSerializer):
    deduction = serializers.SerializerMethodField()
    employee=serializers.SerializerMethodField()
    fixed_amount=serializers.SerializerMethodField()
    percent_of_basic=serializers.SerializerMethodField()
    class Meta:
        model = Deductions
        fields = [
            'id', 'employee', 'deduction', 'quantity', 'amount', 'percent_of_basic',
            'start_date', 'end_date', 'is_active'
        ]

    def get_percent_of_basic(self,obj):
        return 0
    
    def get_fixed_amount(self,obj):
        deduction=obj
        amount=0
        if deduction:
            employee = obj.employee
            salo_details = SalaryDetails.objects.get(employee=employee)
            gross_pay=salo_details.monthly_salary
            if 'n.s.s.f' in str(deduction.deduction.title).lower():
                _, _,employer_contribution = calculate_nssf_contribution(gross_pay)
                obj.employer_amount=employer_contribution
                amount=employer_contribution
            elif 's.h.i.f' in str(deduction.deduction.title).lower() or 'n.h.i.f' in str(deduction.deduction.title).lower():
                _,employee_contribution,employer_contribution = calculate_shif_deduction(gross_pay)
                obj.employer_amount=employer_contribution
                amount=employee_contribution
            elif 'levy' in str(deduction.deduction.title).lower() or 'n.h.i.f' in str(deduction.deduction.title).lower():
                _, employee_contribution,employer_contribution = calculate_other_deduction(gross_pay,title='levy',type='levy')
                amount=employee_contribution
                obj.employer_amount=employer_contribution
            else:
                amount=get_deduction_amount(deduction.deduction,deduction,gross_pay)
        return amount
    
    def get_employee(self,obj):
        employee = obj.employee
        if employee:
            hr_details = HRDetails.objects.get(employee=employee)
            return {
            'name': f'{employee.user.first_name} {employee.user.last_name}',
            'staffNo': hr_details.job_or_staff_number,
            'id': employee.id,
            }
        return None
    
    def get_deduction(self,obj):
        deduction = obj  # This is the deductions instance
        if deduction:
            return {
                "wb_code":deduction.deduction.wb_code,
                "title":deduction.deduction.title,
                "checkoff":deduction.deduction.checkoff,
                "statutory":deduction.deduction.statutory,
                "constant":deduction.deduction.constant,
                "mode":deduction.deduction.mode,
            }
        return None  # Return None if there's no loan

class EarningsSerializer(serializers.ModelSerializer):
    earning = serializers.SerializerMethodField()
    employee=serializers.SerializerMethodField()
    rate=serializers.SerializerMethodField()
    percent_of_basic=serializers.SerializerMethodField()
    class Meta:
        model = Earnings
        fields = [
            'id', 'employee', 'earning', 'quantity', 'amount', 'percent_of_basic',
            'start_date', 'end_date', 'is_active'
        ]

    def get_employee(self,obj):
        employee = obj.employee
        if employee:
            hr_details = HRDetails.objects.get(employee=employee)
            return {
            'name': f'{employee.user.first_name} {employee.user.last_name}',
            'staffNo': hr_details.job_or_staff_number,
            'id': employee.id,
            }
        return None
    
    def get_earning(self,obj):
        earning = obj  
        if earning:
            return {
               "wb_code":earning.earning.wb_code,
               "title":earning.earning.title,
               "checkoff":earning.earning.checkoff,
               "taxable_status":earning.earning.taxable_status,
               "mode":earning.earning.mode,
               }
        return None
    
    def get_percent_of_basic(self,obj):
        return 0
    
    def get_rate(self,obj):
        rate=0
        if obj.employee:
            if obj.earning.mode=='perday':
                rate=SalaryDetails.objects.get(employee=obj.employee).daily_rate
            elif obj.earning.mode=='perhour':
                rate=SalaryDetails.objects.get(employee=obj.employee).hourly_rate
        return rate


class LoansSerializer(serializers.ModelSerializer):
    loan = serializers.SerializerMethodField()
    employee=serializers.SerializerMethodField()
    fringe_benefit_tax=serializers.SerializerMethodField()
    class Meta:
        model = EmployeLoans
        fields = [
            'id', 'employee', 'loan', 'monthly_installment', 'no_of_installments_paid',
            'interest_paid', 'start_date', 'end_date', 'is_active'
        ]

    def get_employee(self,obj):
        employee = obj.employee
        if employee:
            hr_details = HRDetails.objects.get(employee=employee)
            return {
            'name': f'{employee.user.first_name} {employee.user.last_name}',
            'staffNo': hr_details.job_or_staff_number,
            'id': employee.id,
            }
        return None
    
    def get_loan(self, obj):
        employeeLoan = obj  # This is the employeeLoans instance
        if employeeLoan:
            return {
                "wb_code":employeeLoan.loan.wb_code,
                "title":employeeLoan.loan.title,
                "is_active":employeeLoan.loan.is_active,
            }
        return None  # Return None if there's no loan
    
    def get_fringe_benefit_tax(self,obj):
        tax = obj.fringe_benefit_tax  
        if tax:
                return {
                    "id":tax.id,
                    "title":tax.title,
                    "is_current":tax.is_current,
                }
        return None 

class SalaryDetailsDetailSerializer(serializers.ModelSerializer):
    salaryDetail = serializers.SerializerMethodField()
    bank_account_details = EmployeeBankAccountSerializer(source='bank_account', read_only=True)
    work_shift_details = serializers.SerializerMethodField()
    
    class Meta:
        model = SalaryDetails
        fields = [
            'id', 'employee', 'employment_type', 'payment_currency', 'monthly_salary',
            'pay_type', 'work_hours', 'work_shift', 'work_shift_details', 'hourly_rate', 'daily_rate', 'income_tax',
            'deduct_shif_or_nhif', 'deduct_nssf', 'tax_excemption_amount',
            'excemption_cert_no', 'payment_type', 'bank_account', 'bank_account_details', 'mobile_number'
        ]

    def get_salaryDetail(self,obj):
        employee = obj.employee
        hr_details = HRDetails.objects.filter(employee=employee).first()

        salaryDetails = obj  # This is the salaryDetails instance

        if salaryDetails:
            return {
                'currentPay': salaryDetails.monthly_salary,
            }
        return None
    
    def get_work_shift_details(self, obj):
        """Return work shift details including schedule"""
        if obj.work_shift:
            from hrm.attendance.serializers import WorkShiftSerializer
            return WorkShiftSerializer(obj.work_shift).data
        return None  


class PersonalDataSerializer(serializers.ModelSerializer):
    personalData = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            'id', 'user', 'organisation', 'gender', 'passport_photo', 'date_of_birth',
            'residential_status', 'national_id', 'pin_no', 'shif_or_nhif_number',
            'nssf_no', 'deleted', 'terminated'
        ]

    def get_personalData(self, obj):
        
        hr_details = HRDetails.objects.filter(employee=obj).first()  
        employee = obj
        if employee:  
            return {
                'staffNo': hr_details.job_or_staff_number if hr_details else None,  
                'name': f'{employee.user.first_name} {employee.user.last_name}',  
                'Dob': employee.date_of_birth,  
                'gender': employee.gender  
            }
        return None  
 

class HRDetailsSerializer(serializers.ModelSerializer):
    hrData = serializers.SerializerMethodField()

    class Meta:
        model = HRDetails
        fields = [
            'id', 'employee', 'job_or_staff_number', 'job_title', 'department',
            'head_of', 'reports_to', 'region', 'branch', 'project',
            'date_of_employment', 'board_director', 'hrData'
        ]

    def get_hrData(self, obj):
        employee = obj.employee
        hr = obj
        if hr:  
            return {
                'staffNo': hr.job_or_staff_number,
                'name': f'{employee.user.first_name} {employee.user.last_name}', 
                'JobTitle': hr.job_title.title if hr.job_title else None, 
                'Reports to': (
                    {
                        'id': hr.reports_to.user.id,
                        'name': f'{hr.reports_to.user.first_name} {hr.reports_to.user.last_name}',
                        'email': hr.reports_to.user.email
                    } if getattr(hr, 'reports_to', None) and getattr(hr.reports_to, 'user', None) else None
                ),
                'Department': hr.department.title if hr.department else '',
                'Region': hr.region.name if hr.region else ''
            }
        return None  

class ContractSerializer(serializers.ModelSerializer):
    employee = serializers.SerializerMethodField()  # Custom field to return employee data
    class Meta:
        model = Contract
        fields = [
            "id", "employee", "status", "contract_start_date", "contract_end_date",
            "salary", "pay_type", "contract_duration", "notes"
        ]

    def get_employee(self, obj):
        employee = obj.employee
        try:
            hr_details = HRDetails.objects.get(employee=employee)
            staff_no = hr_details.job_or_staff_number
        except HRDetails.DoesNotExist:
            staff_no = 'N/A'
        
        return {
            'id': employee.id,
            'staffNo': staff_no,
            'name': f"{employee.user.first_name} {employee.user.middle_name or ''} {employee.user.last_name}".strip(),
        }

class ContactDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactDetails
        fields = [
            'id', 'employee', 'personal_email', 'country', 'county', 'city',
            'zip', 'address', 'mobile_phone', 'official_phone'
        ]

class NextOfKinSerializer(serializers.ModelSerializer):
    class Meta:
        model = NextOfKin
        fields = [
            'id', 'employee', 'name', 'relation', 'phone', 'email'
        ]

class DocumentsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Documents
        fields = [
            'id', 'employee', 'document_type', 'document_file', 'upload_date',
            'expiry_date', 'is_verified', 'notes'
        ]

class EmployeeSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    salary_details = SalaryDetailsSerializer(many=True, read_only=True)
    hr_details = HRDetailsSerializer(many=True, read_only=True)
    contracts = ContractSerializer(many=True, read_only=True)
    contacts = ContactDetailsSerializer(many=True, read_only=True)
    kins = NextOfKinSerializer(many=True, read_only=True)
    documents = DocumentsSerializer(many=True, read_only=True)

    class Meta:
        model = Employee
        fields = [
            'id', 'user', 'organisation', 'gender', 'passport_photo', 'date_of_birth',
            'residential_status', 'national_id', 'pin_no', 'shif_or_nhif_number',
            'nssf_no', 'deleted', 'terminated', 'allow_ess', 'ess_activated_at', 
            'ess_last_login', 'ess_unrestricted_access', 'salary_details', 'hr_details', 
            'contracts', 'contacts', 'kins', 'documents'
        ]
        read_only_fields = ['ess_activated_at', 'ess_last_login']

class JobTitleSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobTitle
        fields = '__all__'


class JobGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobGroup
        fields = '__all__'


class WorkersUnionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkersUnion
        fields = '__all__'

