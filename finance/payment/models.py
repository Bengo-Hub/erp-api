from django.db import models
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from core.models import BaseModel
from ecommerce.pos.models import Sales
from business.models import Bussiness, Branch
from ecommerce.product.models import Products
from crm.contacts.models import Contact
from finance.accounts.models import PaymentAccounts
from core.models import Departments
from approvals.models import Approval
import uuid

class PaymentMethod(BaseModel):
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)
    requires_verification = models.BooleanField(default=False)
    
    def __str__(self):
        return self.name

class BillingDocument(BaseModel):
    """
    Simplified billing document model for invoices, receipts, and other billing documents
    Focuses on billing-specific functionality, not order management
    """
    INVOICE = 'invoice'
    RECEIPT = 'receipt'
    CREDIT_NOTE = 'credit_note'
    DEBIT_NOTE = 'debit_note'
    QUOTE = 'quote'
    
    DOCUMENT_TYPES = (
        (INVOICE, 'Invoice'),
        (RECEIPT, 'Receipt'),
        (CREDIT_NOTE, 'Credit Note'),
        (DEBIT_NOTE, 'Debit Note'),
        (QUOTE, 'Quote'),
    )
    
    DRAFT = 'draft'
    SENT = 'sent'
    PAID = 'paid'
    CANCELLED = 'cancelled'
    
    STATUS_CHOICES = (
        (DRAFT, 'Draft'),
        (SENT, 'Sent'),
        (PAID, 'Paid'),
        (CANCELLED, 'Cancelled'),
    )
    
    # Core fields
    document_number = models.CharField(max_length=50, unique=True, editable=False)
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    
    # Business context
    business = models.ForeignKey(Bussiness, on_delete=models.CASCADE, related_name='billing_documents', null=True, blank=True)
    branch = models.ForeignKey('business.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    customer = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='billing_documents')
    
    # Link to order (optional - for order-based billing)
    related_order = models.ForeignKey('core_orders.BaseOrder', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Financial fields
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    balance_due = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Dates
    issue_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    
    # User tracking
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_billing_documents')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='updated_billing_documents')
    
    # Notes
    notes = models.TextField(blank=True)
    terms = models.TextField(blank=True)
    
    class Meta(BaseModel.Meta):
        ordering = ['-created_at']
        verbose_name = 'Billing Document'
        verbose_name_plural = 'Billing Documents'
        indexes = [
            models.Index(fields=['document_number'], name='idx_billing_document_number'),
            models.Index(fields=['document_type'], name='idx_billing_document_type'),
            models.Index(fields=['status'], name='idx_billing_document_status'),
            models.Index(fields=['customer'], name='idx_billing_document_customer'),
            models.Index(fields=['issue_date'], name='idx_billing_doc_issue_date'),
            models.Index(fields=['due_date'], name='idx_billing_document_due_date'),
        ]
        
    def __str__(self):
        return f"{self.document_type} #{self.document_number}"
    
    def save(self, *args, **kwargs):
        if not self.document_number:
            self.document_number = self.generate_document_number()
        
        # Calculate balance due
        self.balance_due = self.total - self.amount_paid
        
        # Update status based on payment
        if self.balance_due <= 0 and self.total > 0:
            self.status = self.PAID
        elif self.amount_paid > 0:
            self.status = self.SENT  # Keep as sent if partially paid
            
        super().save(*args, **kwargs)
        
    def generate_document_number(self):
        """Generate unique document number"""
        prefix = {
            self.INVOICE: 'INV',
            self.RECEIPT: 'RCT',
            self.CREDIT_NOTE: 'CRN',
            self.DEBIT_NOTE: 'DBN',
            self.QUOTE: 'QUO',
        }.get(self.document_type, 'DOC')
        
        date_part = timezone.now().strftime('%Y%m%d')
        unique_id = str(uuid.uuid4().int)[:6]
        
        return f"{prefix}-{date_part}-{unique_id}"
        
    def add_payment(self, amount):
        """Add payment to this billing document"""
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero")
        self.amount_paid += amount
        self.save()
        return self.amount_paid, self.balance_due

    def register_payment(self, amount, payment_method, payment_date=None, reference=None,
                         notes=None, account=None, created_by=None):
        """Register a payment against this billing document and update balances."""
        from .models import Payment, PaymentTransaction  # local import to avoid cycles
        payment = Payment.objects.create(
            amount=amount,
            payment_method=payment_method,
            status='completed',
            reference_number=reference or '',
            transaction_id=reference or '',
            payment_date=payment_date or timezone.now(),
            notes=notes or '',
            verified_by=created_by,
        )
        # Optional transaction bookkeeping
        PaymentTransaction.objects.create(
            payment=payment,
            transaction_type='payment',
            amount=amount,
            status='completed',
            transaction_id=payment.transaction_id or payment.reference_number,
            transaction_date=payment.payment_date,
            raw_response=None,
        )
        # Update document amounts
        self.add_payment(amount)
        # Record history
        BillingDocumentHistory.objects.create(
            document=self,
            status=self.status,
            message=f"Payment {amount} via {payment_method} ref {reference or ''}",
            created_by=created_by,
        )
        return payment
    
    @property
    def is_paid(self):
        """Check if document is fully paid"""
        return self.balance_due <= 0
    
    @property
    def is_overdue(self):
        """Check if document is overdue"""
        return self.due_date and self.due_date < timezone.now().date() and not self.is_paid

class BillingItem(BaseModel):
    document = models.ForeignKey(BillingDocument, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1'))
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    subtotal = models.DecimalField(max_digits=15, decimal_places=2)
    total = models.DecimalField(max_digits=15, decimal_places=2)
    
    product = models.ForeignKey(Products, on_delete=models.SET_NULL, null=True, blank=True, related_name='billing_items')
    order_item = models.ForeignKey('core_orders.OrderItem', on_delete=models.SET_NULL, null=True, blank=True, related_name='billing_items')
    
    class Meta(BaseModel.Meta):
        ordering = ['id']
        
    def __str__(self):
        return f"{self.description} - {self.quantity} x {self.unit_price}"
    
    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_price
        self.tax_amount = self.subtotal * (self.tax_rate / 100)
        self.total = self.subtotal + self.tax_amount
        super().save(*args, **kwargs)
        self.update_document_totals()
        
    def update_document_totals(self):
        document = self.document
        from django.db.models import Sum
        aggregates = BillingItem.objects.filter(document=document).aggregate(
            subtotal_sum=Sum('subtotal'),
            tax_sum=Sum('tax_amount'),
            total_sum=Sum('total')
        )
        subtotal_val = aggregates.get('subtotal_sum') or Decimal('0.00')
        tax_val = aggregates.get('tax_sum') or Decimal('0.00')
        total_val = aggregates.get('total_sum') or Decimal('0.00')

        document.subtotal = subtotal_val
        document.tax_amount = tax_val
        document.total = total_val
        document.balance_due = document.total - document.amount_paid
        BillingDocument.objects.filter(pk=document.pk).update(
            subtotal=subtotal_val,
            tax_amount=tax_val,
            total=total_val,
            balance_due=document.balance_due
        )

class Payment(BaseModel):
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('mpesa', 'M-Pesa'),
        ('card', 'Credit/Debit Card'),
        ('paypal', 'PayPal'),
        ('stripe', 'Stripe'),
        ('bank', 'Bank Transfer'),
        ('cod', 'Cash on Delivery'),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
        ('partially_refunded', 'Partially Refunded'),
    ]
    
    MOBILE_MONEY_PROVIDERS = [
        ("mpesa", "M-Pesa"),
    ]
    
    # Core Payment Fields
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    reference_number = models.CharField(max_length=50, unique=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True, help_text="Unified transaction ID for all payment providers")
    
    # Mobile Money Specific Fields (only for mobile money payments)
    mobile_money_provider = models.CharField(max_length=20, choices=MOBILE_MONEY_PROVIDERS, blank=True, null=True, help_text="Mobile money provider used for payment")
    phone_number = models.CharField(max_length=15, blank=True, null=True, help_text="Phone number used for mobile money payment")
    
    # Payment Processing Fields
    payment_processor = models.CharField(max_length=50, blank=True, null=True, help_text="Payment processor used (e.g., Safaricom)")
    processor_response = models.JSONField(blank=True, null=True, help_text="Full response from payment processor")
    processing_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Processing fee charged by payment provider")
    
    # Kenyan Market Specific Fields
    kra_compliance = models.BooleanField(default=False, help_text="Whether payment complies with KRA requirements")
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Tax amount included in payment")
    tax_reference = models.CharField(max_length=50, blank=True, null=True, help_text="KRA tax reference number")
    
    # Timestamps
    payment_date = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(blank=True, null=True, help_text="When payment was processed")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    verification_date = models.DateTimeField(null=True, blank=True)
    
    # Notes
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.reference_number} - {self.amount} ({self.payment_method})"

    def save(self, *args, **kwargs):
        if not self.reference_number:
            self.reference_number = self.generate_reference_number()
        
        # Set mobile money provider based on payment method
        if self.payment_method in ['mpesa']:
            self.mobile_money_provider = self.payment_method
        
        # Set payment processor based on method
        if self.payment_method == 'mpesa':
            self.payment_processor = 'Safaricom'
        elif self.payment_method == 'card':
            self.payment_processor = 'Stripe'
        elif self.payment_method == 'paypal':
            self.payment_processor = 'PayPal'
            
        super().save(*args, **kwargs)
        
    def generate_reference_number(self):
        """Generate unique payment reference number"""
        prefix = 'PAY'
        date_part = timezone.now().strftime('%Y%m%d')
        unique_id = str(uuid.uuid4().int)[:6]
        return f"{prefix}-{date_part}-{unique_id}"
            
    class Meta(BaseModel.Meta):
        db_table = 'finance_payments'
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
        indexes = [
            models.Index(fields=['payment_method'], name='idx_payment_method'),
            models.Index(fields=['status'], name='idx_payment_status'),
            models.Index(fields=['reference_number'], name='idx_payment_reference'),
            models.Index(fields=['transaction_id'], name='idx_payment_transaction'),
            models.Index(fields=['payment_date'], name='idx_payment_date'),
            models.Index(fields=['mobile_money_provider'], name='idx_payment_mobile_provider'),
            models.Index(fields=['phone_number'], name='idx_payment_phone'),
            models.Index(fields=['kra_compliance'], name='idx_payment_kra_compliance'),
            models.Index(fields=['created_at'], name='idx_payment_created_at'),
        ]

class BillingDocumentHistory(BaseModel):
    document = models.ForeignKey(BillingDocument, on_delete=models.CASCADE, related_name='history')
    status = models.CharField(max_length=20, choices=BillingDocument.STATUS_CHOICES)
    message = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    
    class Meta(BaseModel.Meta):
        ordering = ['-created_at']
        verbose_name_plural = 'Billing document histories'
        
    def __str__(self):
        return f"History for {self.document.document_number} at {self.created_at}"

# BillingApproval moved to centralized approvals app - import from there

class POSPayment(Payment):
    sale = models.ForeignKey(Sales, on_delete=models.CASCADE, related_name='payments')
    change_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    tendered_amount = models.DecimalField(max_digits=10, decimal_places=2)

    def save(self, *args, **kwargs):
        if not self.reference_number:
            self.reference_number = f"POS-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        super().save(*args, **kwargs)

class PaymentTransaction(BaseModel):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20)  # e.g., 'payment', 'refund', 'chargeback'
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20)
    transaction_id = models.CharField(max_length=100)
    transaction_date = models.DateTimeField(default=timezone.now)
    raw_response = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"{self.transaction_id} - {self.amount}"

class PaymentRefund(BaseModel):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='refunds')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    refund_date = models.DateTimeField(default=timezone.now)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, default='pending')
    refund_transaction_id = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"Refund for {self.payment.reference_number} - {self.amount}"
