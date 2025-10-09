from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.db import models
from django.conf import settings
from django.utils import timezone
from authmanagement.models import CustomUser
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from djmoney.models.fields import MoneyField
from core.models import OvertimeRate, PartialMonthPay
from approvals.models import Approval
from hrm.employees.models import Employee
from decimal import Decimal

User=get_user_model()

# Create your models here.
class Relief(models.Model):
    relief_types=[
        ("Personal","Personal Relief"),
        ("Deductible","Deductible Relief"),
    ]
    component_choices=[
        ("Actual","Actual Amount"),
        ("Basic","Basic Pay"),
        ("Basic_benefits","Basic and Benefits"),
        ("Basic_benefit_minus_this_benefit","Basic and(Benefits - This Benefit)"),
    ]
    type=models.CharField(max_length=255,choices=relief_types)
    title=models.CharField(max_length=255)
    actual_amount=models.BooleanField(default=True)
    fixed_limit=models.DecimalField(max_digits=14, decimal_places=4,default=Decimal('0.00'))
    percentage=models.DecimalField(max_digits=14, decimal_places=4,default=Decimal('0.00'))
    percent_of=models.CharField(max_length=255,choices=component_choices,default=None,blank=True,null=True)
    is_active=models.BooleanField(default=False)
   
    def __str__(self) -> str:
        return self.title 

    class Meta:
        verbose_name_plural="Reliefs"
        #db_table="reliefs"
        managed=True

class Formulas(models.Model):
    types=[
        ("income","Income Tax Formula"),
        ("deduction","Deduction Formula"),
        ("earning","Earning Formula"),
        ("fbt","Fridge Benefit Tax Formula"),
        ("levy","Levy Formula"),
        ("relief_allowance","Relief Allowance Formula")
    ]
    categories=[
        ("primary","P.A.Y.E Primary Employee"),
        ("secondary","P.A.Y.E Secondary Employee"),
        ("fbt","Fridge Benefit Tax"),
        ("housing_levy","Housing Levy"),
        ("social_security_fund","Social Security Fund"),
        ("nhif","NHIF Contributions"),
        ("shif","SHIF Contributions")
    ]
    type=models.CharField(max_length=100,choices=types,verbose_name='Formala Type',default=None,blank=True,null=True)
    deduction=models.ForeignKey("PayrollComponents",on_delete=models.CASCADE,related_name="formulas",blank=True,null=True)
    category=models.CharField(max_length=100,choices=categories,default=None,blank=True,null=True)
    title=models.CharField(max_length=255,default='P.A.Y.E Kenya - 2023')
    unit=models.CharField(max_length=100,default='KES')
    effective_from=models.DateField(null=True,blank=True,default=None)
    effective_to=models.DateField(null=True,blank=True,default=None)
    upper_limit=models.DecimalField(max_digits=14, decimal_places=4,default=Decimal('0.00'))
    upper_limit_amount=models.DecimalField(max_digits=14, decimal_places=4,default=Decimal('0.00'),help_text='Deduction Amount')
    upper_limit_percentage=models.DecimalField(max_digits=10,decimal_places=2,default=Decimal('0.00'),help_text='Deduction Percentage')
    personal_relief=models.DecimalField(max_digits=14, decimal_places=4,default=Decimal('0.00'),null=True,blank=True)
    relief_carry_forward=models.BooleanField(default=False)
    min_taxable_income=models.DecimalField(max_digits=14, decimal_places=4,default=Decimal('0.00'),null=True,blank=True)
    progressive=models.BooleanField(default=False)
    created_at=models.DateField(blank=True,null=True)
    is_current=models.BooleanField(default=False)
    
    # New fields for enhanced formula management
    version = models.CharField(max_length=20, default='1.0', blank=True, null=True, help_text='Formula version number')
    transition_date = models.DateField(null=True, blank=True, help_text='Date when this formula transitioned from previous version')
    replaces_formula = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='replaced_by', help_text='Formula this replaces')
    regulatory_source = models.CharField(max_length=255, blank=True, null=True, help_text='Source of regulatory change (e.g., Finance Act 2023)')
    notes = models.TextField(blank=True, null=True, help_text='Additional notes about this formula')
    
    # New field for deduction ordering
    deduction_order = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text='JSON array defining deduction sequence for this formula version'
    )
    
    # Example deduction_order:
    # [
    #     {"phase": "before_tax", "components": ["nssf", "shif", "housing_levy"]},
    #     {"phase": "after_tax", "components": ["paye"]},
    #     {"phase": "after_paye", "components": ["loans", "advances"]}
    # ]

    def save(self, *args, **kwargs):
        #if self.is_current:  # Only set other formulas to False if this one is current
            # Set all current formulas to False
            #Formulas.objects.filter(is_current=True).update(is_current=False)
        super(Formulas,self).save(*args, **kwargs)

    def get_effective_formula(self, payroll_date):
        """Get the formula effective for a specific payroll date"""
        if payroll_date >= self.effective_from:
            if not self.effective_to or payroll_date <= self.effective_to:
                return self
        return None

    def is_effective_for_date(self, payroll_date):
        """Check if this formula is effective for a given payroll date"""
        if not self.effective_from:
            return False
        if payroll_date < self.effective_from:
            return False
        if self.effective_to and payroll_date > self.effective_to:
            return False
        return True
    
    @property
    def is_historical(self):
        """Check if this formula is historical (no longer effective)"""
        from django.utils import timezone
        today = timezone.now().date()
        return self.effective_to and self.effective_to < today

    def __str__(self) -> str:
        return f"{self.title} (v{self.version}) - {self.effective_from} to {self.effective_to or 'Current'}" 

    class Meta:
        verbose_name_plural="Formulas"
        #db_table="formulas"
        managed=True
        ordering = ['-effective_from', '-version']
        indexes = [
            models.Index(fields=['type', 'category', 'effective_from']),
            models.Index(fields=['is_current']),
            models.Index(fields=['version']),
        ]

class SplitRatio(models.Model):
    formula=models.ForeignKey(Formulas,on_delete=models.CASCADE,related_name="sliptrations")
    employee_percentage=models.DecimalField(max_digits=10,decimal_places=2,default=Decimal('0.00'))
    employer_percentage=models.DecimalField(max_digits=10,decimal_places=2,default=Decimal('0.00'))

class FormulaItems(models.Model):
    formula=models.ForeignKey(Formulas,on_delete=models.CASCADE,related_name="formulaitems")
    amount_from=models.DecimalField(max_digits=14, decimal_places=4,default=Decimal('0.00'))
    amount_to=models.DecimalField(max_digits=14, decimal_places=4,default=Decimal('0.00'))
    deduct_amount=models.DecimalField(max_digits=14, decimal_places=4,default=Decimal('0.00'))
    deduct_percentage=models.DecimalField(max_digits=10,decimal_places=4,default=Decimal('0.00'))
    

    def __str__(self) -> str:
        return self.formula.title 

    class Meta:
        verbose_name_plural="Formula Rates"
        #db_table="formulaitems"
        managed=True

class WithHoldingtax(models.Model):
    """Model for withholding tax calculations and rates."""
    title = models.CharField(max_length=255, help_text="Name of the withholding tax", default="Default Tax")
    rate = models.DecimalField(max_digits=5, decimal_places=2, help_text="Tax rate percentage", default=Decimal('0.00'))
    threshold = models.DecimalField(max_digits=15, decimal_places=2, help_text="Minimum amount for tax application", default=Decimal('0.00'))
    is_active = models.BooleanField(default=True, help_text="Whether this tax rate is currently active")
    effective_from = models.DateField(null=True, blank=True, help_text="Date from which this rate is effective")
    effective_to = models.DateField(null=True, blank=True, help_text="Date until which this rate is effective")
    
    class Meta:
        verbose_name_plural = "Withholding Taxes"
        ordering = ['-effective_from']
    
    def __str__(self):
        return f"{self.title} - {self.rate}%"

# Create your models here.
class BenefitTaxes(models.Model):
    component_choices=[
        (None,None),
        ("Actual","Actual Amount"),
        ("Basic","Basic Pay"),
        ("Basic_benefits","Basic and Benefits"),
        ("Basic_benefit_minus_this_benefit","Basic and(Benefits - This Benefit)"),
    ]
    title=models.CharField(max_length=255)
    actual_amount=models.BooleanField(default=True)
    fixed_limit=MoneyField(max_digits=14, decimal_places=4, default_currency='KES', default=0.00)
    percentage=models.DecimalField(max_digits=14, decimal_places=4,default=Decimal('0.00'))
    percent_of=models.CharField(max_length=255,choices=component_choices,default=None,blank=True,null=True)
    amounts_greater_than=MoneyField(max_digits=14, decimal_places=4, default_currency='KES', default=0.00)
    min_taxable_aggregate=MoneyField(max_digits=14, decimal_places=4, default_currency='KES', default=3000.00)
   
    def __str__(self) -> str:
        return self.title 

    class Meta:
        verbose_name_plural="Benefit Taxes"
        #db_table="benefittaxes"
        managed=True

class SeverancePay(models.Model):
    no_of_days_per_complete_employment_year=models.PositiveIntegerField(default=15)

    class Meta:
        verbose_name_plural="Severance Pay"

    def __str__(self):
        return str(self.no_of_days_per_complete_employment_year)

class MarketLengingRates(models.Model):
    year=models.IntegerField(default=2024)
    month=models.IntegerField(default=1)

    def __str__(self) -> str:
        return str(self.year )

    class Meta:
        verbose_name_plural="Market Lending Rates"
        #db_table="MarketLengingRates"
        managed=True

class RepayOption(models.Model):
    amount=models.DecimalField(max_digits=14, decimal_places=2)
    no_of_installments=models.PositiveIntegerField(default=1)
    installment_amount=models.DecimalField(max_digits=14, decimal_places=2, blank=True,null=True,help_text="Auto calculated field")

    def save(self, *args, **kwargs):
        # Ensure that the number of installments is greater than 0 to avoid division by zero
        if self.no_of_installments > 0:
            # Calculate the installment amount
            self.installment_amount = self.amount // self.no_of_installments
        else:
            # Handle case where no_of_installments is 0 (to avoid division by zero)
            self.installment_amount = Decimal('0.00')
        # Call the parent save method to save the object
        super().save(*args, **kwargs)


    def __str__(self) -> str:
        return f"{self.no_of_installments} Installments (s) - amount {self.installment_amount}" 

    class Meta:
        verbose_name_plural="Repayment Options"
        managed=True

class PayrollComponents(models.Model):
    CATEGORY_CHOICES = [
        ('Benefits', 'Benefits'),
        ('Earnings', 'Earnings'),
        ('Deductions', 'Deductions'),
    ]
    MODE_CHOICES = [
         (None, None),
        ('monthly', 'Monthly'),
        ('weekly', 'Weekly'),
        ('daily', 'Daily'),
        ('perhour', 'Per Hour'),
        ('perday', 'Per Day'),
        ('perpiece', 'Per Piece'),
        ('commission', 'Commission'),
    ]
    TAXABLE_STATUSES = [
        (None, None),
        ('taxable', 'Taxable'),
        ('nontaxable', 'Non-Taxable'),
        ('lowincome', 'Low Income Non-Taxable'),
        ('gratuity', 'Gratuity Tax'),
    ]
    wb_code = models.CharField(max_length=20, blank=True, null=True)
    acc_code = models.CharField(max_length=20, blank=True, null=True)
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES,blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES,default='monthtly',blank=True,null=True)
    non_cash= models.BooleanField(default=False)
    deduct_after_taxing = models.BooleanField(default=False)
    applicable_relief = models.ForeignKey(Relief,on_delete=models.SET_NULL,related_name='payrollcomponents',null=True,blank=True)
    applicable_tax_formula = models.ForeignKey(BenefitTaxes,on_delete=models.SET_NULL,related_name='payrollcomponents',null=True,blank=True)
    checkoff = models.BooleanField(default=True,help_text='Deduct on employee\'s behalf?')
    constant = models.BooleanField(default=True)
    statutory = models.BooleanField(default=False,help_text='Mandatory by Law?')
    is_active = models.BooleanField(default=True)
    taxable_status = models.CharField(max_length=100,choices=TAXABLE_STATUSES,default=None,blank=True,null=True)
    
    # New fields for deduction ordering
    deduction_phase = models.CharField(
        max_length=20,
        choices=[
            ('before_tax', 'Before Tax (NSSF, SHIF, Housing Levy)'),
            ('after_tax', 'After Tax (PAYE)'),
            ('after_paye', 'After PAYE (Loans, Advances)'),
            ('final', 'Final (Non-cash benefits)')
        ],
        default='before_tax',
        blank=True,
        null=True,
        help_text='Phase in which this deduction/component is applied'
    )
    
    deduction_priority = models.PositiveIntegerField(
        default=1,
        blank=True,
        null=True,
        help_text='Order within the same phase (lower = earlier)'
    )

    def __str__(self) -> str:
        return f"{self.title}" 

    class Meta:
        verbose_name_plural="Payroll Components"
        #db_table="payroll_components"
        managed=True

class Loans(models.Model):
    wb_code=models.CharField(max_length=100)
    account_code=models.CharField(max_length=100,null=True,blank=True)
    title=models.CharField(max_length=100)
    is_active=models.BooleanField(default=False)
    round_off = models.DecimalField(max_digits=2,default=Decimal('0.00'),decimal_places=2,blank=True, null=True)

    def __str__(self) -> str:
        return self.title
    
    class Meta:
        verbose_name_plural="Loans"
        #db_table="formulaitems"
        managed=True

class DefaultPayrollSettings(models.Model):
    default_deductions=models.ManyToManyField(PayrollComponents,blank=True,null=True,related_name='default_deductions')
    default_earnings=models.ManyToManyField(PayrollComponents,blank=True,null=True,related_name='default_earnings')
    default_benefits=models.ManyToManyField(PayrollComponents,blank=True,null=True,related_name="default_benefits")

    class Meta:
        verbose_name_plural="Default Payroll Settings"
    
    def __str__(self):
        return "default setting"

class ScheduledPayslip(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Sent', 'Sent'),
        ('Failed', 'Failed'),
    ]

    DELIVERY_STATUS_CHOICES = [
        ('Delivered', 'Delivered'),
        ('Failed', 'Failed'),
    ]

    date = models.DateField(default=now)
    document_type = models.CharField(max_length=50, default="Payslips")
    composer = models.ForeignKey(CustomUser,on_delete=models.SET_NULL,null=True)
    payroll_period = models.DateField()  
    recipients = models.ManyToManyField(Employee)
    scheduled_time = models.DateTimeField()
    send_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    delivery_status = models.CharField(max_length=20, choices=DELIVERY_STATUS_CHOICES, default='Failed')
    comments = models.TextField(null=True, blank=True)


    def __str__(self):
        return f"{self.document_type} ({self.payroll_period}) by {self.composer}"


class GeneralHR(models.Model):
    overtime_rates = models.ManyToManyField(OvertimeRate, related_name="hr_settings")
    partial_month_pay = models.OneToOneField(PartialMonthPay, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return 'General HR'



# PayrollApproval moved to centralized approvals app - import from there


# Payroll approval models removed - using centralized approval system from approvals app