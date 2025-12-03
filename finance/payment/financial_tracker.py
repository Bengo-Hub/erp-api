"""
CRITICAL: Financial Transaction Tracker
Single Source of Truth for ALL Money Movements in the Organization
Integrates: Invoices, Expenses, Purchase Orders, Payroll, Refunds
"""
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils import timezone
from decimal import Decimal
from core.models import BaseModel


class FinancialTransaction(BaseModel):
    """
    Universal Financial Transaction Tracker
    Records EVERY money movement regardless of source module
    Provides unified financial reporting and audit trail
    """
    TRANSACTION_TYPES = [
        # Money IN (Revenue)
        ('invoice_payment', 'Invoice Payment'),
        ('sales_payment', 'Sales Payment'),
        ('refund_received', 'Refund Received'),
        ('advance_received', 'Advance Received'),
        
        # Money OUT (Expenses)
        ('expense_payment', 'Expense Payment'),
        ('purchase_order_payment', 'Purchase Order Payment'),
        ('payroll_payment', 'Payroll Payment'),
        ('supplier_payment', 'Supplier Payment'),
        ('tax_payment', 'Tax Payment'),
        ('refund_issued', 'Refund Issued'),
        ('loan_payment', 'Loan Payment'),
        
        # Internal
        ('transfer', 'Account Transfer'),
        ('adjustment', 'Balance Adjustment'),
    ]
    
    DIRECTION_CHOICES = [
        ('in', 'Money In'),
        ('out', 'Money Out'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('reversed', 'Reversed'),
    ]
    
    # Transaction Identification
    transaction_number = models.CharField(max_length=100, unique=True, blank=True)
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    
    # Financial Details
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=3, default='KES')
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal('1.0000'))
    
    # Link to Source Document (Generic)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    source_document = GenericForeignKey('content_type', 'object_id')
    source_reference = models.CharField(max_length=100, help_text="Reference number from source document")
    
    # Link to Finance Payment
    payment = models.OneToOneField('payment.Payment', on_delete=models.PROTECT, related_name='financial_transaction')
    
    # Account Tracking
    payment_account = models.ForeignKey('accounts.PaymentAccounts', on_delete=models.PROTECT)
    
    # Party Tracking
    party_name = models.CharField(max_length=255, help_text="Customer/Supplier name")
    party_contact = models.ForeignKey('crm.Contact', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Status and Approval
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requires_approval = models.BooleanField(default=False)
    approved_by = models.ForeignKey('authmanagement.CustomUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_transactions')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    # Dates
    transaction_date = models.DateTimeField(default=timezone.now)
    value_date = models.DateField(help_text="Date when transaction value is realized")
    
    # Reconciliation
    is_reconciled = models.BooleanField(default=False)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey('authmanagement.CustomUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciled_transactions')
    
    # Metadata
    notes = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True, help_text="Tags for categorization")
    
    class Meta:
        verbose_name = 'Financial Transaction'
        verbose_name_plural = 'Financial Transactions'
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['transaction_number'], name='idx_fin_trans_number'),
            models.Index(fields=['transaction_type'], name='idx_fin_trans_type'),
            models.Index(fields=['direction'], name='idx_fin_trans_direction'),
            models.Index(fields=['status'], name='idx_fin_trans_status'),
            models.Index(fields=['transaction_date'], name='idx_fin_trans_date'),
            models.Index(fields=['value_date'], name='idx_fin_trans_value_date'),
            models.Index(fields=['payment_account'], name='idx_fin_trans_account'),
            models.Index(fields=['party_contact'], name='idx_fin_trans_party'),
            models.Index(fields=['is_reconciled'], name='idx_fin_trans_reconciled'),
            models.Index(fields=['content_type', 'object_id'], name='idx_fin_trans_source'),
        ]
    
    def save(self, *args, **kwargs):
        if not self.transaction_number:
            self.transaction_number = self.generate_transaction_number()
        
        if not self.value_date:
            self.value_date = self.transaction_date.date()
        
        super().save(*args, **kwargs)
    
    def generate_transaction_number(self):
        """Generate unique transaction number"""
        prefix = 'TXN'
        date_part = timezone.now().strftime('%Y%m%d')
        count = FinancialTransaction.objects.filter(
            created_at__date=timezone.now().date()
        ).count() + 1
        return f"{prefix}-{date_part}-{count:05d}"
    
    def approve_transaction(self, user):
        """Approve the transaction"""
        self.status = 'approved'
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at'])
    
    def complete_transaction(self):
        """Mark transaction as completed"""
        self.status = 'completed'
        self.save(update_fields=['status'])
    
    def reconcile_transaction(self, user):
        """Mark transaction as reconciled"""
        self.is_reconciled = True
        self.reconciled_at = timezone.now()
        self.reconciled_by = user
        self.save(update_fields=['is_reconciled', 'reconciled_at', 'reconciled_by'])
    
    def __str__(self):
        return f"{self.transaction_number} - {self.get_transaction_type_display()} - {self.amount}"
    
    @classmethod
    def create_from_payment(cls, payment, source_document, source_reference):
        """
        Factory method to create FinancialTransaction from Payment
        Automatically links payment to source document
        """
        # Get party name
        party_name = ""
        party_contact = None
        if payment.customer:
            party_name = payment.customer.business_name or f"{payment.customer.user.first_name} {payment.customer.user.last_name}"
            party_contact = payment.customer
        elif payment.supplier:
            party_name = payment.supplier.business_name or f"{payment.supplier.user.first_name} {payment.supplier.user.last_name}"
            party_contact = payment.supplier
        
        # Create transaction
        transaction = cls.objects.create(
            transaction_type=payment.payment_type,
            direction=payment.direction,
            amount=payment.amount,
            payment=payment,
            payment_account=payment.payment_account,
            party_name=party_name,
            party_contact=party_contact,
            content_type=ContentType.objects.get_for_model(source_document),
            object_id=source_document.id,
            source_reference=source_reference,
            status='completed' if payment.status == 'completed' else 'pending',
            transaction_date=payment.payment_date,
        )
        
        return transaction

