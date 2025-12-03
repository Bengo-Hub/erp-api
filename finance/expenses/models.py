from django.db import models
from django.utils import timezone
from crm.contacts.models import Contact
from business.models import Branch,TaxRates,Bussiness
from finance.accounts.models import PaymentAccounts
from ecommerce.pos.models import Register

from django.contrib.auth import get_user_model
User=get_user_model()

class ExpenseCategory(models.Model):
    name = models.CharField(max_length=255)

    class Meta:
        verbose_name_plural='Expense Categories'
        indexes = [
            models.Index(fields=['name'], name='idx_expense_category_name'),
        ]

    def __str__(self):
        return self.name

class Expense(models.Model):
    register = models.ForeignKey(Register, on_delete=models.CASCADE, related_name='expenses', blank=True, null=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='expenses')
    category = models.ForeignKey(ExpenseCategory, on_delete=models.CASCADE,related_name='category_expenses')
    reference_no = models.CharField(max_length=100)
    date_added = models.DateField()
    expense_for_user = models.ForeignKey(User, on_delete=models.CASCADE,related_name='user_expenses',blank=True, null=True)
    expense_for_contact = models.ForeignKey(Contact, on_delete=models.CASCADE,related_name='conatct_expenses',blank=True, null=True)
    attach_document = models.FileField(upload_to='expense/documents/', blank=True, null=True)
    applicable_tax = models.ForeignKey(TaxRates,on_delete=models.SET_NULL,related_name='expense_taxes',blank=True, null=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    expense_note = models.TextField(blank=True, null=True)
    is_refund = models.BooleanField(default=False)
    is_recurring = models.BooleanField(default=False)
    interval_type= models.CharField(max_length=50,choices=[("Daily","Daily"),("Weekly","Weekly"),("Monthly","Monthly"),("Yearly","Yearly")],blank=True, null=True)
    recurring_interval=models.PositiveIntegerField(default=0)
    repetitions = models.IntegerField(default=0)

    class Meta:
        verbose_name_plural='Expenses'
        indexes = [
            models.Index(fields=['register'], name='idx_expense_register'),
            models.Index(fields=['branch'], name='idx_expense_branch'),
            models.Index(fields=['category'], name='idx_expense_category'),
            models.Index(fields=['reference_no'], name='idx_expense_reference_no'),
            models.Index(fields=['date_added'], name='idx_expense_date_added'),
            models.Index(fields=['expense_for_user'], name='idx_expense_for_user'),
            models.Index(fields=['expense_for_contact'], name='idx_expense_for_contact'),
            models.Index(fields=['applicable_tax'], name='idx_expense_tax'),
            models.Index(fields=['is_refund'], name='idx_expense_is_refund'),
            models.Index(fields=['is_recurring'], name='idx_expense_is_recurring'),
        ]

    def __str__(self):
        return self.reference_no

class ExpensePayment(models.Model):
    """Link model to connect expenses with centralized payments"""
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='expense_payments', blank=True, null=True)
    payment = models.ForeignKey('payment.Payment', on_delete=models.CASCADE, related_name='expense_payments')
    payment_account = models.ForeignKey(PaymentAccounts, on_delete=models.CASCADE, related_name='expense_payment_accounts', blank=True, null=True)
    payment_note = models.TextField(blank=True, null=True)
    paid_on = models.DateField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Expense Payments'
        indexes = [
            models.Index(fields=['expense'], name='idx_expense_payment_expense'),
            models.Index(fields=['payment'], name='idx_expense_payment_payment'),
            models.Index(fields=['paid_on'], name='idx_expense_payment_paid_on'),
            models.Index(fields=['payment_account'], name='idx_expense_payment_account'),
        ]

    def __str__(self):
        return f"{self.expense.reference_no} - {self.payment.reference_number}"
    
    @property
    def amount(self):
        return self.payment.amount
    
    @property
    def payment_method(self):
        return self.payment.payment_method
    
    @property
    def status(self):
        return self.payment.status


class ExpenseEmailLog(models.Model):
    """Track all emails sent for expenses - similar to Invoice email tracking"""
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='email_logs')
    email_type = models.CharField(max_length=20, choices=[
        ('sent', 'Expense Report Sent'),
        ('approval_request', 'Approval Request'),
        ('approved', 'Approval Notification'),
        ('rejected', 'Rejection Notification'),
        ('payment_request', 'Payment Request'),
    ])
    recipient_email = models.EmailField()
    sent_at = models.DateTimeField(default=timezone.now)
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default='sent', choices=[
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('opened', 'Opened'),
        ('clicked', 'Clicked'),
        ('bounced', 'Bounced'),
        ('failed', 'Failed'),
    ])
    
    class Meta:
        verbose_name = 'Expense Email Log'
        verbose_name_plural = 'Expense Email Logs'
        ordering = ['-sent_at']
    
    def __str__(self):
        return f"{self.expense.reference_no} - {self.get_email_type_display()} to {self.recipient_email}"
