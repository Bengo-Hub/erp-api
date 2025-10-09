# finance/accounts/models.py
from django.db import models
from authmanagement.models import CustomUser
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils.translation import gettext_lazy as _
from decimal import Decimal

from django.contrib.auth import get_user_model
User=get_user_model()
# Define the Kenyan phone number regex pattern
kenyan_phone_regex = r"^(?:\+?254|0)(?:\d{9}|\d{3}\s\d{3}\s\d{3}|\d{2}\s\d{3}\s\d{3})$"

class AccountTypes(models.Model):
    name=models.CharField(max_length=100)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'account_types'
        verbose_name = 'Account Types'
        verbose_name_plural = 'Account Types'
        indexes = [
            models.Index(fields=['name'], name='idx_account_types_name'),
        ]

# Create your models here.
class PaymentAccounts(models.Model):
    name=models.CharField(max_length=255)
    account_number=models.CharField(max_length=16)
    account_type=models.ForeignKey(AccountTypes,on_delete=models.CASCADE,related_name="paymentaccounts")
    opening_balance=models.DecimalField(max_digits=10,decimal_places=2,default=Decimal('0.00'))

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'payment_accounts'
        verbose_name = 'Payment Accounts'
        verbose_name_plural = 'Payment Accounts'
        indexes = [
            models.Index(fields=['name'], name='idx_payment_accounts_name'),
            models.Index(fields=['account_number'], name='idx_payment_accounts_number'),
            models.Index(fields=['account_type'], name='idx_payment_accounts_type'),
        ]

class TransactionPayment(models.Model):
    TRANSACTION_TYPES = (
        ('Sale', 'Sale'),
        ('Purchase', 'Purchase'),
        ('Expense', 'Expense'),
    )

    transaction_type = models.CharField(_('Transaction Type'), max_length=50, choices=TRANSACTION_TYPES)
    ref_no = models.CharField(_('Transaction ID'), max_length=100)
    amount_paid = models.DecimalField(_('Amount'), max_digits=14, decimal_places=2, default=Decimal('0.00'))
    payment = models.ForeignKey('payment.Payment', on_delete=models.CASCADE, related_name='transaction_payments')
    payment_account = models.ForeignKey(PaymentAccounts, on_delete=models.SET_NULL, related_name='transaction_payments', blank=True, null=True)
    payment_note = models.TextField(_('Payment Note'), blank=True, null=True)
    payment_document = models.FileField(_('Attachment'), upload_to='payments/attachments', blank=True, null=True)
    paid_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name=_('Paid By'), related_name='paid_by_payments')
    paid_to = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name=_('Paid To'), related_name='paid_to_payments')
    payment_date = models.DateTimeField(_('Payment Date'), auto_now_add=True, blank=True, null=True)

    class Meta:
        verbose_name = _('Transaction Payment')
        verbose_name_plural = _('Transaction Payments')
        indexes = [
            models.Index(fields=['transaction_type'], name='idx_transaction_payment_type'),
            models.Index(fields=['ref_no'], name='idx_transaction_payment_ref_no'),
            models.Index(fields=['payment'], name='idx_txn_pay_payment'),
            models.Index(fields=['payment_account'], name='idx_txn_pay_account'),
            models.Index(fields=['paid_by'], name='idx_txn_paid_by'),
            models.Index(fields=['paid_to'], name='idx_txn_paid_to'),
            models.Index(fields=['payment_date'], name='idx_txn_pay_date'),
        ]

    def __str__(self):
        return f"{self.transaction_type} Payment - {self.ref_no}"
    
    @property
    def payment_method(self):
        return self.payment.payment_method
    
    @property
    def status(self):
        return self.payment.status
    
    @property
    def transaction_id(self):
        return self.payment.transaction_id
    
    @property
    def mobile_money_provider(self):
        return self.payment.mobile_money_provider
    
    @property
    def phone_number(self):
        return self.payment.phone_number

class Voucher(models.Model):
    VOUCHER_STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Paid', 'Paid'),
    ]

    VOUCHER_TYPE_CHOICES = [
        ('Payment', 'Payment'),
        ('Journal', 'Journal'),
        ('Adjustment', 'Adjustment'),
    ]

    reference_number = models.CharField(max_length=20, unique=True)
    voucher_type = models.CharField(max_length=50, choices=VOUCHER_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=10, default='KES')
    voucher_date = models.DateField()
    status = models.CharField(max_length=20, choices=VOUCHER_STATUS_CHOICES, default='Pending')
    remarks = models.TextField(null=True, blank=True)
    # Polymorphic link to specific voucher details
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    details = GenericForeignKey('content_type', 'object_id')

    def __str__(self):
        return f"Voucher {self.reference_number} - {self.status}"

    class Meta:
        verbose_name = "Voucher"
        verbose_name_plural = "Vouchers"
        ordering = ['-voucher_date']
        indexes = [
            models.Index(fields=['reference_number'], name='idx_voucher_reference'),
            models.Index(fields=['voucher_type'], name='idx_voucher_type'),
            models.Index(fields=['voucher_date'], name='idx_voucher_date'),
            models.Index(fields=['status'], name='idx_voucher_status'),
            models.Index(fields=['content_type', 'object_id'], name='idx_voucher_content'),
        ]

class VoucherItem(models.Model):
    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(null=True, blank=True, default=1)  # Optional for non-PO vouchers
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Enhanced accounting fields
    debit_account = models.ForeignKey('PaymentAccounts', on_delete=models.CASCADE, related_name='debit_voucher_items', null=True, blank=True)
    credit_account = models.ForeignKey('PaymentAccounts', on_delete=models.CASCADE, related_name='credit_voucher_items', null=True, blank=True)
    account_type = models.CharField(max_length=50, choices=[
        ('debit', 'Debit'),
        ('credit', 'Credit'),
        ('both', 'Both')
    ], default='both')
    
    # Additional metadata
    reference = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        verbose_name = "Voucher Item"
        verbose_name_plural = "Voucher Items"
        ordering = ['id']
        indexes = [
            models.Index(fields=['voucher'], name='idx_voucher_item_voucher'),
            models.Index(fields=['debit_account'], name='idx_vitem_debit_acct'),
            models.Index(fields=['credit_account'], name='idx_vitem_credit_acct'),
            models.Index(fields=['account_type'], name='idx_vitem_acct_type'),
        ]

    def __str__(self):
        return f"Item: {self.description} - Amount: {self.amount}"
    
    def save(self, *args, **kwargs):
        """Auto-calculate amount if not provided"""
        if not self.amount and self.quantity and self.unit_price:
            self.amount = self.quantity * self.unit_price
        super().save(*args, **kwargs)

class VoucherAudit(models.Model):
    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name='audits')
    action = models.CharField(max_length=50, choices=[('Created', 'Created'), ('Approved', 'Approved'), ('Rejected', 'Rejected'), ('Paid', 'Paid')])
    action_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='voucher_audits')
    action_date = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Audit for Voucher {self.voucher.reference_number} - {self.action}"

    class Meta:
        indexes = [
            models.Index(fields=['voucher'], name='idx_voucher_audit_voucher'),
            models.Index(fields=['action'], name='idx_voucher_audit_action'),
            models.Index(fields=['action_by'], name='idx_voucher_audit_action_by'),
            models.Index(fields=['action_date'], name='idx_voucher_audit_action_date'),
        ]


class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('income', 'Income'),
        ('expense', 'Expense'),
        ('transfer', 'Transfer'),
        ('payment', 'Payment'),
        ('refund', 'Refund'),
        ('adjustment', 'Adjustment'),
    ]
    
    account = models.ForeignKey(PaymentAccounts, on_delete=models.CASCADE, related_name='transactions')
    transaction_date = models.DateTimeField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    transaction_type = models.CharField(max_length=50, choices=TRANSACTION_TYPES)
    description = models.TextField()
    reference_type = models.CharField(max_length=100, help_text='Type of document this transaction relates to (invoice, expense, etc.)')
    reference_id = models.CharField(max_length=100, help_text='ID of the referenced document')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_transactions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-transaction_date']
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'
        indexes = [
            models.Index(fields=['transaction_date'], name='idx_transaction_date'),
            models.Index(fields=['transaction_type'], name='idx_transaction_type'),
            models.Index(fields=['reference_type', 'reference_id'], name='idx_transaction_reference'),
            models.Index(fields=['account'], name='idx_transaction_account'),
            models.Index(fields=['created_by'], name='idx_transaction_created_by'),
            models.Index(fields=['created_at'], name='idx_transaction_created_at'),
        ]
    
    def __str__(self):
        return f"{self.transaction_type.capitalize()} - {self.amount} - {self.transaction_date.strftime('%Y-%m-%d')}"
        
    def is_debit(self):
        """Return True if this transaction decreases the account balance"""
        return self.transaction_type in ['expense', 'payment', 'transfer']
        
    def is_credit(self):
        """Return True if this transaction increases the account balance"""
        return self.transaction_type in ['income', 'refund']
