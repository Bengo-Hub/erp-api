from datetime import timedelta
from decimal import Decimal
from django.db import models
from djmoney.models.fields import MoneyField
from hrm.employees.models import Employee, HRDetails, SalaryDetails
from hrm.payroll_settings.models import *
from django.contrib.auth import get_user_model
User=get_user_model()


class EmployeLoans(models.Model):
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="employeeloans",blank=True,null=True)
    loan=models.ForeignKey(Loans,on_delete=models.CASCADE,related_name='employeeloans',blank=True,null=True)
    principal_amount=models.DecimalField(max_digits=14, decimal_places=4,default=0.00)
    amount_repaid=models.DecimalField(max_digits=14, decimal_places=4,default=0.00)
    interest_paid=models.DecimalField(max_digits=14, decimal_places=4,default=0.00)
    no_of_installments_paid=models.PositiveIntegerField(default=0)
    monthly_installment=models.DecimalField(max_digits=14, decimal_places=4,default=0.00)
    interest_rate=models.DecimalField(max_digits=10,decimal_places=2,default=0.00)
    interest_formula=models.CharField(max_length=100,choices=[("Reducing Balance","Reducing Balance"),("Fixed","Fixed")],blank=True,null=True,default=None)
    fringe_benefit_tax=models.ForeignKey(Formulas,on_delete=models.SET_DEFAULT,related_name='employee_loans',default=None,blank=True,null=True)
    is_active=models.BooleanField(default=False)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    def save(self, *args, **kwargs):
        # Calculate the end date if start date and number of installments are provided
        if self.start_date and self.monthly_installment > 0:
            # Assuming monthly installments, calculate end date
            self.end_date = self.start_date + timedelta(days=30 * int(self.principal_amount/self.monthly_installment))
        else:
            self.end_date = None  # Reset if conditions aren't met
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.loan.title

    class Meta:
        verbose_name_plural="Employee Loans"
        db_table="employee_loans"
        managed=True

class Advances(models.Model):
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="advances")
    approver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    approved=models.BooleanField(default=False)
    issue_date=models.DateField()
    repay_option=models.ForeignKey(RepayOption,on_delete=models.CASCADE,related_name="advances",null=True,blank=True)
    prev_payment_date=models.DateField(blank=True,null=True)
    next_payment_date=models.DateField()
    amount_issued=models.DecimalField(max_digits=14, decimal_places=2,default=0,help_text="Auto calculated field")
    amount_repaid=models.DecimalField(max_digits=14, decimal_places=2,default=0,blank=True,null=True,help_text="Auto calculated field")
    is_active=models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Ensure that the number of installments is greater than 0 to avoid division by zero
        if self.repay_option is not None:
            # Calculate the installment amount
            self.amount_issued = self.repay_option.amount
        else:
            # Handle case where no_of_installments is 0 (to avoid division by zero)
            self.amount_issued = 0
        if self.amount_repaid is None:
            self.amount_repaid=0.00
        # Call the parent save method to save the object
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.employee.user.email

    class Meta:
        verbose_name_plural="Employee Advances"
        db_table="employee_advances"
        managed=True

class LossesAndDamages(models.Model):
    description=models.CharField(max_length=1500,blank=True,null=True)
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="loss_damages",blank=True,null=True)
    approver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    approved=models.BooleanField(default=False)    
    issue_date=models.DateField()
    repay_option=models.ForeignKey(RepayOption,on_delete=models.CASCADE,related_name='lossdamages',null=True,blank=True)
    prev_payment_date=models.DateField(blank=True,null=True)
    next_payment_date=models.DateField()
    damage_amount=models.DecimalField(max_digits=14, decimal_places=2)
    amount_repaid=models.DecimalField(max_digits=14, decimal_places=2)
    is_active=models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Ensure that the number of installments is greater than 0 to avoid division by zero
        if self.repay_option is not None:
            # Calculate the installment amount
            self.amount_issued = self.repay_option.amount
        else:
            # Handle case where no_of_installments is 0 (to avoid division by zero)
            self.amount_issued = 0
        if self.amount_repaid is None:
            self.amount_repaid=0.00
        # Call the parent save method to save the object
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.employee.user.email

    class Meta:
        verbose_name_plural="Losses & Damages"
        db_table="employee_losses_and_damages"
        managed=True

class ExpenseClaims(models.Model):
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="expense_claims")
    approver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    approved=models.BooleanField(default=False)
    category=models.CharField(max_length=100,choices=(("Other","Other"),("Mileage","Mileage")))
    application_date=models.DateField()
    payment_date=models.DateField(blank=True,null=True)
    attachment=models.FileField(upload_to="claim_attachments",blank=True,null=True)
    amount=models.DecimalField(max_digits=14,decimal_places=2,default=0)
    is_active=models.BooleanField(default=True)
    is_paid=models.BooleanField(default=False)
    schedule_to_payroll=models.BooleanField(default=False)
    delete_status=models.BooleanField(default=False)


    def __str__(self) -> str:
        return self.employee.user.email

    class Meta:
        verbose_name_plural="Expense Claims"
        db_table="employee_expense_claims"
        managed=True

class ClaimItems(models.Model):
    expense_choices=(
        ("tt","Travel Tickets"),
        ("ac","Accommodation"),
        ("ml","Meals"),
        ("jm","Job Materials"),
        ("os","Office Supplies"),
    )
    claim=models.ForeignKey(ExpenseClaims,on_delete=models.CASCADE,related_name="expense_categories")
    expense_type=models.CharField(max_length=100,choices=expense_choices)
    application_date=models.DateField()
    description=models.TextField()
    place_from=models.CharField(max_length=100,blank=True,null=True,help_text="Only applies for millage claims")
    place_to=models.CharField(max_length=100,blank=True,null=True,help_text="Only applies for millage claims")
    quantity_or_distance=models.FloatField()
    unit_cost_or_rate=models.FloatField()
    amount=models.DecimalField(max_digits=14, decimal_places=2)

    def save(self,*args,**kwargs):
        self.amount=self.quantity_or_distance*self.unit_cost_or_rate
        super().save(*args,**kwargs)

    def __str__(self) -> str:
        return self.claim.category

    class Meta:
        verbose_name_plural="Claim Items"
        managed=True

class Deductions(models.Model):
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="deductions",blank=True,null=True)
    deduction=models.ForeignKey(PayrollComponents,on_delete=models.CASCADE,related_name="deductions")
    paid_to_date=models.DecimalField(max_digits=14,decimal_places=2,default=0.00)
    quantity=models.DecimalField(max_digits=10,decimal_places=4,default=0,help_text="Quantity per amount chargable, leave default if using fixed amount")
    amount=models.DecimalField(max_digits=14,decimal_places=4,default=0,help_text="Fixed or per quantity")
    employer_amount=models.DecimalField(max_digits=14,decimal_places=4,default=0,help_text="Fixed or percentage og Basic Pay")
    is_active = models.BooleanField(default=True)
    effective_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    def __str__(self) -> str:
        return self.deduction.title
    
    def save(self,*args,**kwargs):
        super(Deductions,self).save(*args,**kwargs)
        # Modify the amount and calculate employer contribution only if quantity > 0
        if self.pk is None and self.quantity > 0:
            # Calculate the new amount
            self.amount = self.amount * self.quantity
            self.employer_amount=0
            # Fetch the related formula and split ratio
            formula = Formulas.objects.filter(deduction=self).first()
            if formula:
                ratio = SplitRatio.objects.get(formula=formula)
                # Convert to Decimal to handle arithmetic correctly
                employee_percentage = Decimal(ratio.employee_percentage)
                employer_percentage = Decimal(ratio.employer_percentage)
                
                # Calculate the total and employer amount
                total = (100 * Decimal(self.amount)) / employee_percentage
                employer_amount = (total * employer_percentage) / Decimal('100')
                self.employer_amount = employer_amount
        else:
            self.employer_amount=0
            # Fetch the related formula and split ratio
            formula = Formulas.objects.filter(deduction=self.deduction).first()
            if formula:
                ratio = SplitRatio.objects.get(formula=formula)
                # Convert to Decimal to handle arithmetic correctly
                employee_percentage = Decimal(ratio.employee_percentage)
                employer_percentage = Decimal(ratio.employer_percentage)
                
                # Calculate the total and employer amount
                total = (100 * Decimal(self.amount)) / employee_percentage
                employer_amount = (total * employer_percentage) / Decimal('100')
                self.employer_amount = employer_amount
        super(Deductions, self).save(update_fields=["amount", "employer_amount"])

    class Meta:
        verbose_name_plural="Employee Deductions"
        db_table="employee_deductions"
        managed=True

class Benefits(models.Model):
    TYPES=[
        ("Employer's Owned House","Employer's Owned House"),
        ("Employer's Rented House","Employer's Rented House"),
        ("Agricultural Farm","Agricultural Farm"),
    ]
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="benefits",blank=True,null=True)
    benefit=models.ForeignKey(PayrollComponents,on_delete=models.CASCADE,related_name="benefits")
    amount=models.DecimalField(max_digits=14,decimal_places=4,default=0)
    is_active = models.BooleanField(default=True)
    effective_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    def __str__(self) -> str:
        return self.benefit.title

    class Meta:
        db_table="employee_benefits"
        verbose_name_plural="Employee Benefits"
        managed=True

class Earnings(models.Model):
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name="earnings",blank=True,null=True)
    earning=models.ForeignKey(PayrollComponents,on_delete=models.CASCADE,related_name="earnings")
    quantity=models.DecimalField(max_digits=10,decimal_places=4,default=0,help_text="Quantity per amount chargable, leave default if using fixed amount")
    rate=models.DecimalField(max_digits=10,decimal_places=4,default=0,help_text="Rate")
    amount=models.DecimalField(max_digits=14,decimal_places=4,default=0,help_text="Fixed or per quantity")
    is_active = models.BooleanField(default=True)
    effective_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    def __str__(self) -> str:
        return self.earning.title
    
    def save(self,*args,**kwargs):
        # Check if this is a new instance (creation)
        if self.pk is None and self.quantity > 0:
            # Only modify the amount when creating the entry
            if self.earning.mode=='perday':
                daily_rate=SalaryDetails.objects.get(employee=self.employee).daily_rate
                self.rate=daily_rate
            if self.earning.mode=='perhour':
                hourly_rate=SalaryDetails.objects.get(employee=self.employee).hourly_rate
                self.rate=hourly_rate
            self.amount = self.rate * self.quantity
        super(Earnings,self).save(*args,**kwargs)

    class Meta:
        db_table="employee_earnings"
        verbose_name_plural="Employee Earnings"
        managed=True

class Payslip(models.Model):
    approvalstatuses=(
        ("draft","Draft"),
        ("pending","Pending"),
        ("approved","Approved"),
        ("rejected","Rejected")
    )
    payrollstatuses=(
        ("complete","Complete"),
        ("expired","Expired"),
        ("processing","Processing"),
        ("queued","Queued")
    )
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    created_by=models.ForeignKey(CustomUser,on_delete=models.SET_NULL,null=True,blank=True,related_name='payslip_creator')
    # Core payroll amounts
    gross_pay = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Total gross pay before deductions")
    total_earnings = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Total earnings and benefits")
    net_pay = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Final net pay after all deductions")
    
    # Tax calculation fields
    taxable_pay = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Pay subject to tax calculation")
    paye = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Pay As You Earn tax amount")
    tax_relief = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Personal relief amount")
    reliefs = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Total tax reliefs applied")
    gross_pay_after_tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Gross pay after tax deductions")
    
    # Component-specific amounts
    shif_or_nhif_contribution = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="NHIF contribution amount (legacy)")
    housing_levy = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Housing Levy amount")
    nssf_employee_tier_1 = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="NSSF Tier 1 contribution")
    nssf_employee_tier_2 = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="NSSF Tier 2 contribution")
    nssf_employer_contribution = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="NSSF employer contribution")
    
    # Deduction phase fields for dynamic deduction ordering
    deductions_before_tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Total deductions applied before tax calculation")
    deductions_after_tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Total deductions applied after tax calculation")
    deductions_after_paye = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Total deductions applied after PAYE calculation")
    deductions_final = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Final deductions (non-cash benefits, etc.)")
    payment_period = models.DateField(null=True, blank=True)
    payroll_status=models.CharField(max_length=100,choices=payrollstatuses,default="queued")
    approval_status=models.CharField(max_length=100,choices=payrollstatuses,default="draft")
    approver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,related_name='payslip_approver')
    published=models.BooleanField(default=False)
    payroll_date = models.DateField(auto_now=True)
    period_start = models.DateField(blank=True, null=True)
    period_end = models.DateField(blank=True, null=True)
    # KRA PAYE filing metadata
    kra_paye_reference = models.CharField(max_length=100, blank=True, null=True)
    kra_filed_at = models.DateTimeField(blank=True, null=True)
    delete_status=models.BooleanField(default=False)

    def __str__(self):
        return f"{self.employee} - {self.payment_period.strftime('%B %Y')}"

    class Meta:
        verbose_name_plural = "Payslips"
        db_table = "payslips"
        managed = True
        indexes = [
            models.Index(fields=['employee'], name='idx_payslip_employee'),
            models.Index(fields=['payment_period'], name='idx_payslip_period'),
        ]

class PayslipAudit(models.Model):
    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name='payslips')
    action = models.CharField(max_length=50, choices=[('Created', 'Created'), ('Approved', 'Approved'), ('Rejected', 'Rejected'), ('Nulled', 'Nulled'), ('Draft', 'Draft')])
    action_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='payslip_audits')
    action_date = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Audit for Payroll {self.payslip.payment_period} - {self.action}" 
    