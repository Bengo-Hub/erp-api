from decimal import Decimal
from django.db import models
from authmanagement.models import CustomUser
from django.core.validators import RegexValidator
from djmoney.models.fields import MoneyField
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField
from business.models import Bussiness
from core.models import Regions,Projects,Departments,BankInstitution,BankBranches
from django.utils.translation import gettext_lazy as _
from datetime import datetime

# Define the Kenyan phone number regex pattern
kenyan_phone_regex = r"^(?:\+?254|0)(?:\d{9}|\d{3}\s\d{3}\s\d{3}|\d{2}\s\d{3}\s\d{3})$"

# Create a RegexValidator instance using the regex pattern
kenyan_phone_validator = RegexValidator(
    regex=kenyan_phone_regex,
    message="Please enter a valid Kenyan phone number."
)
# mobile_num_regex = RegexValidator(
#     regex=r"^(?:\+254|0)[17]\d{8}$", message="Entered mobile number isn't in a right format!"
# )

class Employee(models.Model):
    GENDER = [("male", "Male"), ("female", "Female"), ("other", "Other")]
    user=models.OneToOneField(CustomUser,on_delete=models.CASCADE,verbose_name="Employee ESS")#id,first_name,last
    organisation=models.ForeignKey(Bussiness,on_delete=models.CASCADE,blank=True,null=True,related_name="employees")
    gender = models.CharField(max_length=10, choices=GENDER)
    passport_photo = models.ImageField(
        upload_to='passports', blank=True, null=True)
    date_of_birth = models.DateField()
    residential_status=models.CharField(max_length=50,choices=(("Resident","Resident"),("Non-Resident","Non-Resident")))
    national_id=models.CharField(max_length=20,unique=True,verbose_name="National ID")
    pin_no=models.CharField(max_length=16)
    shif_or_nhif_number=models.CharField(
        max_length=16,
        verbose_name="SHIF/NHIF Number",
        help_text="SHIF number (2024+) or NHIF number (pre-2024)",
        blank=True,
        null=True
    )
    nssf_no=models.CharField(max_length=16)
    deleted=models.BooleanField(default=False)
    terminated=models.BooleanField(default=False)
    
    # ESS (Employee Self-Service) Access
    allow_ess = models.BooleanField(
        default=False,
        verbose_name="Allow ESS Access",
        help_text="Enable Employee Self-Service portal access for this employee"
    )
    ess_activated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="ESS Activated On",
        help_text="Date when ESS access was first activated"
    )
    ess_last_login = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="ESS Last Login",
        help_text="Last time employee logged into ESS portal"
    )
    ess_unrestricted_access = models.BooleanField(
        default=False,
        verbose_name="Unrestricted ESS Access",
        help_text="Allow ESS login regardless of shift rotation, off days, or leave status. Only for managers/supervisors."
    )

    def __str__(self) -> str:
        return self.user.email
    
    def can_login_to_ess(self):
        """
        Check if employee can login to ESS based on shift rotation, off days, and leave status.
        Returns: (can_login: bool, reason: str)
        """
        from django.utils import timezone
        from hrm.leave.models import LeaveRequest
        
        # Check if ESS access is enabled
        if not self.allow_ess:
            return False, "ESS access is disabled for this employee"
        
        # Check if account is terminated or deleted
        if self.terminated:
            return False, "Employee account has been terminated"
        
        if self.deleted:
            return False, "Employee account has been deleted"
        
        # Load ESS settings - import locally to avoid circular dependency
        try:
            from hrm.attendance.models import ESSSettings
            ess_settings = ESSSettings.load()
        except:
            # If settings don't exist yet (before migration), default to allowing login
            ess_settings = None
        
        # ALWAYS allow superusers (is_superuser=True)
        if self.user.is_superuser:
            return True, "Superuser access"
        
        # Check if shift-based restrictions are globally disabled
        if ess_settings and not ess_settings.enable_shift_based_restrictions:
            return True, "Shift restrictions disabled globally"
        
        # Check if user's role is exempt
        if ess_settings and ess_settings.is_role_exempt(self.user):
            return True, "Exempt role access"
        
        # Managers/supervisors with unrestricted access can always login
        if self.ess_unrestricted_access:
            return True, "Unrestricted access granted"
        
        # Check if user has staff permissions (but not superuser - already checked above)
        if self.user.is_staff:
            return True, "Administrator access"
        
        today = timezone.now().date()
        current_day = today.strftime('%A')  # Get day name (Monday, Tuesday, etc.)
        
        # Check weekend override setting
        if ess_settings and ess_settings.allow_weekend_login and current_day in ['Saturday', 'Sunday']:
            return True, "Weekend login allowed by settings"
        
        # Check if employee has salary details with shift assignment
        try:
            salary_detail = self.salary_details.filter().first()
            if not salary_detail or not salary_detail.work_shift:
                # No shift assigned, allow login (default behavior)
                return True, "No shift restrictions"
            
            work_shift = salary_detail.work_shift
            
            # Check if today is a working day in the shift schedule
            schedule_today = work_shift.schedule.filter(day=current_day).first()
            if schedule_today and not schedule_today.is_working_day:
                return False, f"Today ({current_day}) is not a working day in your shift schedule"
            
            # Check if employee is on an off day
            if self.off_days.filter(date=today).exists():
                return False, "You have an off day today"
            
            # Check if employee is on approved leave
            active_leave = LeaveRequest.objects.filter(
                employee=self,
                start_date__lte=today,
                end_date__gte=today,
                status='approved'
            ).first()
            
            if active_leave:
                return False, f"You are currently on {active_leave.leave_type.name} leave"
            
            # Check shift rotation if applicable
            rotation = work_shift.current_rotations.filter(is_active=True).first()
            if rotation and rotation.current_active_shift != work_shift:
                return False, f"Your current active shift is {rotation.current_active_shift.name}"
            
            # All checks passed
            return True, "Login permitted"
            
        except Exception as e:
            # If any error occurs, default to allowing login
            print(f"Error checking ESS login eligibility: {e}")
            return True, "Login permitted (default)"

    class Meta:
        ordering=['id']
        verbose_name_plural="Employees"
        db_table="employee"
        managed=True
        indexes = [
            models.Index(fields=['user'], name='idx_employee_user'),
            models.Index(fields=['organisation'], name='idx_employee_organisation'),
            models.Index(fields=['gender'], name='idx_employee_gender'),
            models.Index(fields=['date_of_birth'], name='idx_employee_dob'),
            models.Index(fields=['national_id'], name='idx_employee_national_id'),
            models.Index(fields=['pin_no'], name='idx_employee_pin_no'),
            models.Index(fields=['deleted'], name='idx_employee_deleted'),
            models.Index(fields=['terminated'], name='idx_employee_terminated'),
            models.Index(fields=['allow_ess'], name='idx_employee_allow_ess'),
            models.Index(fields=['ess_activated_at'], name='idx_employee_ess_activated'),
            models.Index(fields=['ess_unrestricted_access'], name='idx_employee_ess_unrestricted'),
        ]

class EmployeeBankAccount(models.Model):
    """Employee bank account details for salary payments"""
    
    ACCOUNT_TYPES = [
        ('savings', 'Savings Account'),
        ('current', 'Current Account'),
        ('checking', 'Checking Account'),
        ('salary', 'Salary Account'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('suspended', 'Suspended'),
        ('closed', 'Closed'),
    ]
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='bank_accounts')
    bank_institution = models.ForeignKey(BankInstitution, on_delete=models.CASCADE, related_name='employee_accounts')
    bank_branch = models.ForeignKey(BankBranches, on_delete=models.SET_NULL, null=True, blank=True, related_name='employee_accounts')
    
    # Account details
    account_name = models.CharField(max_length=255, help_text="Account holder name as it appears in bank records")
    account_number = models.CharField(max_length=20, help_text="Bank account number")
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES, default='savings')
    # Status and metadata
    is_primary = models.BooleanField(default=False, help_text="Primary account for salary payments")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    is_verified = models.BooleanField(default=False, help_text="Whether account details have been verified")
    
    # Dates
    opened_date = models.DateField(blank=True, null=True, help_text="Date account was opened")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.employee.user.get_full_name()} - {self.bank_institution.name} ({self.account_number})"
    
    def save(self, *args, **kwargs):
        # Ensure only one primary account per employee
        if self.is_primary:
            EmployeeBankAccount.objects.filter(employee=self.employee, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)
    
    class Meta:
        db_table = 'employee_bank_accounts'
        verbose_name = 'Employee Bank Account'
        verbose_name_plural = 'Employee Bank Accounts'
        unique_together = ['employee', 'account_number', 'bank_institution']
        indexes = [
            models.Index(fields=['employee'], name='idx_emp_bank_account_employee'),
            models.Index(fields=['bank_institution'], name='idx_emp_bank_account_bank'),
            models.Index(fields=['account_number'], name='idx_emp_bank_account_number'),
            models.Index(fields=['is_primary'], name='idx_emp_bank_account_primary'),
            models.Index(fields=['status'], name='idx_emp_bank_account_status'),
        ]

class SalaryDetails(models.Model):
    employment_type_choices=(
        ("regular-open","Regular(open-ended)"),
        ("regular-fixed","Regular(fixed-term)"),
        ("intern","Intern"),
        ("probationary","Probationary"),
        ("casual","Casual"),
        ("consultant","Consultant"),
    )
    pay_choices=(
        ("basic","Basic Pay"),
        ("gross","Gross Pay(Incl. Benefits(computed))"),
        ("consolidated","Consolidated Pay(Incl. Benefits(non-computed))"),
        ("net_pay","Net Pay")
    )
    income_tax_options=(
        ("primary","P.A.Y.E Primary Employee"),
        ("secondary","P.A.Y.E Secondary Employee"),
    )
    pay_options=(
        ("bank","Bank Transfer"),
        ("mobile_payment","Mobile Money"),
        ("cash","Cash"),
        ("cheque","Cheque"),
    )
    ###########General###############################
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name='salary_details')
    employment_type=models.CharField(max_length=100,choices=employment_type_choices)
    payment_currency=models.CharField(max_length=10,default='KES')
    monthly_salary = models.DecimalField(max_digits=14, decimal_places=2)
    pay_type=models.CharField(max_length=100,choices=pay_choices,default="gross")
    work_hours=models.IntegerField(default=8)
    work_shift=models.ForeignKey('attendance.WorkShift', on_delete=models.SET_NULL, blank=True, null=True, related_name='salary_details', help_text="Work shift assigned to employee")
    hourly_rate=models.DecimalField(max_digits=14,decimal_places=2,blank=True,null=True,help_text="auto calculated field")
    daily_rate=models.DecimalField(max_digits=14,decimal_places=2,blank=True,null=True,help_text="auto calculated field")
    income_tax=models.CharField(max_length=200,choices=income_tax_options,default="primary")
    deduct_shif_or_nhif=models.BooleanField(
        default=True,
        verbose_name="Deduct SHIF/NHIF",
        help_text="Whether to deduct SHIF (2024+) or NHIF (pre-2024)",
        blank=True,
        null=True
    )
    deduct_nssf=models.BooleanField(default=True)
    ############Tax Excemption##########################
    tax_excemption_amount=models.DecimalField(max_digits=14,decimal_places=2,blank=True,null=True)
    excemption_cert_no=models.CharField(max_length=255,blank=True,null=True)
    ###########payment options#############################
    payment_type=models.CharField(max_length=50,choices=pay_options,default="bank",help_text="Leave all fields below blank if cash or cheque is selected")
    bank_account=models.ForeignKey(EmployeeBankAccount,on_delete=models.SET_NULL,blank=True,null=True,help_text="Primary bank account for salary payments")
    mobile_number=models.CharField(max_length=15,blank=True,null=True,help_text="Only fill if payment option is Mobile Money")

    def __str__(self) -> str:
        return self.employee.user.email
    
    def save(self, *args, **kwargs):
        if self.pk is None:
            # Assuming 22 working days in a month
            working_days_in_month = 22        
            # Calculate daily rate: monthly_salary / working days in the month
            if self.monthly_salary:
                self.daily_rate = round(self.monthly_salary / working_days_in_month)
            # Calculate hourly rate: daily_rate / work_hours
            if self.daily_rate and self.work_hours > 0:
                self.hourly_rate = round(self.daily_rate / self.work_hours)
            # Call the original save method
        super(SalaryDetails, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural="Salary Details"
        db_table="employee_salary_details"
        managed=True
        indexes = [
            models.Index(fields=['employee'], name='idx_salary_details_employee'),
            models.Index(fields=['employment_type'], name='idx_salary_details_emp_type'),
            models.Index(fields=['payment_currency'], name='idx_salary_details_currency'),
            models.Index(fields=['pay_type'], name='idx_salary_details_pay_choice'),
            models.Index(fields=['income_tax'], name='idx_salary_details_income_tax'),
            models.Index(fields=['payment_type'], name='idx_salary_details_pay_type'),
            models.Index(fields=['bank_account'], name='idx_salary_details_bank_acc'),
            models.Index(fields=['work_shift'], name='idx_salary_details_work_shift'),
        ]

class JobTitle(models.Model):
    title=models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.title

    class Meta:
        db_table="jobtitles"
        managed=True
        indexes = [
            models.Index(fields=['title'], name='idx_job_title_title'),
        ]


class JobGroup(models.Model):
    """Job groups for employee classification"""
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.title

    class Meta:
        db_table = "job_groups"
        managed = True
        verbose_name_plural = "Job Groups"
        indexes = [
            models.Index(fields=['title'], name='idx_job_group_title'),
        ]


class WorkersUnion(models.Model):
    """Workers unions and labor associations"""
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    registration_number = models.CharField(max_length=100, blank=True, null=True)
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    contact_phone = models.CharField(max_length=20, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        db_table = "workers_unions"
        managed = True
        verbose_name_plural = "Workers Unions"
        indexes = [
            models.Index(fields=['name'], name='idx_workers_union_name'),
            models.Index(fields=['code'], name='idx_workers_union_code'),
        ]


class HRDetails(models.Model):
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="hr_details")
    job_or_staff_number=models.CharField(max_length=100,verbose_name="Job/Staff Number")
    job_title = models.ForeignKey(JobTitle, on_delete=models.SET_NULL, null=True, blank=True, related_name="hr_details_job_title")
    department = models.ForeignKey(Departments, on_delete=models.CASCADE, related_name="hr_details_department", blank=True, null=True)
    head_of = models.ForeignKey(Departments, on_delete=models.CASCADE, related_name="hr_details_head_of", blank=True, null=True)
    reports_to = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="hr_details_reports_to", blank=True, null=True)
    region = models.ForeignKey(Regions, on_delete=models.CASCADE, related_name="hr_details", blank=True, null=True)
    branch = models.ForeignKey('business.Branch', on_delete=models.CASCADE, related_name="hr_details", blank=True, null=True, help_text="Branch where employee works")
    project = models.ForeignKey(Projects, on_delete=models.CASCADE, related_name="hr_details", blank=True, null=True)
    date_of_employment=models.DateField()
    board_director=models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.employee.user.email

    class Meta:
        verbose_name_plural="HR Details"
        db_table="employee_hr_details"
        managed=True
        indexes = [
            models.Index(fields=['employee'], name='idx_hr_details_employee'),
            models.Index(fields=['job_or_staff_number'], name='idx_hr_details_job_number'),
            models.Index(fields=['job_title'], name='idx_hr_details_job_title'),
            models.Index(fields=['department'], name='idx_hr_details_department'),
            models.Index(fields=['head_of'], name='idx_hr_details_head_of'),
            models.Index(fields=['reports_to'], name='idx_hr_details_reports_to'),
            models.Index(fields=['region'], name='idx_hr_details_region'),
            models.Index(fields=['branch'], name='idx_hr_details_branch'),
            models.Index(fields=['project'], name='idx_hr_details_project'),
            models.Index(fields=['date_of_employment'], name='idx_hr_details_employment_date'),
            models.Index(fields=['board_director'], name='idx_hr_details_board_director'),
        ]

class Contract(models.Model):
    pay_choices=(
        ("basic","Basic Pay"),
        ("gross","Gross Pay(Incl. Benefits(computed))"),
        ("consolidated","Consolidated Pay(Incl. Benefits(non-computed))"),
        ("net_pay","Net Pay")
    )
    statuses=(
        ("active","Active"),
        ("suspended","Suspended"),
        ("terminated","Terminated"),
        ("expired","Expired")
    )
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name='contracts')
    contract_start_date=models.DateField()
    contract_end_date=models.DateField()
    status=models.CharField(max_length=100,choices=statuses,default="active")
    salary = models.DecimalField(max_digits=14, decimal_places=2)
    pay_type=models.CharField(max_length=100,choices=pay_choices)
    contract_duration=models.DecimalField(max_digits=10,decimal_places=2,blank=True, null=True,help_text="Duration In Days. This is an auto calculated field. DO NOT FILL!")
    notes=models.TextField(blank=True,null=True)

    def save(self, *args, **kwargs):
        # Calculate contract duration if start and end dates are provided
        if self.contract_start_date and self.contract_end_date:
            start_date = datetime.strptime(str(self.contract_start_date), "%Y-%m-%d")
            end_date = datetime.strptime(str(self.contract_end_date), "%Y-%m-%d")
            duration = int((end_date - start_date).days)
            self.contract_duration = Decimal(f"{duration:.2f}") 
        super(Contract,self).save(*args, **kwargs)

    def __str__(self) -> str:
        return self.employee.user.email

    class Meta:
        ordering=['contract_start_date']
        managed=True
        indexes = [
            models.Index(fields=['employee'], name='idx_contract_employee'),
            models.Index(fields=['contract_start_date'], name='idx_emp_contract_start'),
            models.Index(fields=['contract_end_date'], name='idx_emp_contract_end'),
            models.Index(fields=['status'], name='idx_emp_contract_status'),
            models.Index(fields=['pay_type'], name='idx_contract_pay_type'),
        ]

class ContactDetails(models.Model):
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="contacts")
    personal_email = models.EmailField(unique=True)
    country = CountryField(max_length=255,default='KE', blank=True, null=True)
    county=models.CharField(max_length=255)
    city=models.CharField(max_length=255,verbose_name="City/Town")
    zip=models.CharField(max_length=6,verbose_name="Zip/Postal Code")
    address=models.TextField()
    mobile_phone = PhoneNumberField(default='+254743793901',validators=[kenyan_phone_validator])
    official_phone = PhoneNumberField(default='+254743793901',validators=[kenyan_phone_validator])
    
    def __str__(self) -> str:
        return self.employee.user.email

    class Meta:
        verbose_name_plural="Contact Details"
        db_table="employee_contact_details"
        managed=True
        indexes = [
            models.Index(fields=['employee'], name='idx_contact_details_employee'),
            models.Index(fields=['personal_email'], name='idx_contact_details_email'),
            models.Index(fields=['country'], name='idx_contact_details_country'),
            models.Index(fields=['county'], name='idx_contact_details_county'),
            models.Index(fields=['city'], name='idx_contact_details_city'),
        ]
   
class NextOfKin(models.Model):
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="kins")
    name=models.CharField(max_length=255)
    relation=models.CharField(max_length=255)
    phone = PhoneNumberField(default='254743793901',validators=[kenyan_phone_validator])
    email=models.EmailField(unique=True)

    def __str__(self) -> str:
        return self.employee.user.email

    class Meta:
        verbose_name_plural="Next Of Kins"
        db_table="employee_kin_details"
        managed=True
        indexes = [
            models.Index(fields=['employee'], name='idx_next_of_kin_employee'),
            models.Index(fields=['name'], name='idx_next_of_kin_name'),
            models.Index(fields=['relation'], name='idx_next_of_kin_relation'),
            models.Index(fields=['email'], name='idx_next_of_kin_email'),
        ]

class Documents(models.Model):
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="documents")
    document=models.FileField(upload_to="Employee Documents")

    def __str__(self) -> str:
        return self.document.name if self.document else "Not uploaded"

    class Meta:
        verbose_name_plural="Documents"
        db_table="employee_documents"
        managed=True
        indexes = [
            models.Index(fields=['employee'], name='idx_documents_employee'),
        ]
    
