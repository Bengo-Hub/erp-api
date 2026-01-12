from django.db import models
from django.utils import timezone
import logging
from django.core.validators import MinValueValidator
from django.contrib.auth import get_user_model
from decimal import Decimal
from core.models import BaseModel
from core_orders.models import BaseOrder
from crm.contacts.models import Contact
from business.models import Branch, Bussiness
from business.document_service import DocumentNumberService, DocumentType
from finance.accounts.models import PaymentAccounts
from approvals.models import Approval
import uuid
from django.db.models import Sum
from core.audit import AuditTrail

User = get_user_model()
logger = logging.getLogger(__name__)


class Invoice(BaseOrder):
    """
    Invoice Model - Comprehensive invoice management like Zoho Invoice
    Extends BaseOrder for order-line items and financial tracking
    Serves as Money-IN source for Finance module
    """
    # Invoice Status - Extended from Zoho workflow
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('viewed', 'Viewed'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
        ('void', 'Void'),
    ]
    
    PAYMENT_TERMS = [
        ('due_on_receipt', 'Due on Receipt'),
        ('net_15', 'Net 15'),
        ('net_30', 'Net 30'),
        ('net_45', 'Net 45'),
        ('net_60', 'Net 60'),
        ('net_90', 'Net 90'),
        ('custom', 'Custom'),
    ]
    
    TEMPLATE_CHOICES = [
        ('standard', 'Standard Template'),
        ('modern', 'Modern Template'),
        ('classic', 'Classic Template'),
        ('professional', 'Professional Template'),
    ]
    
    # Invoice specific identifiers
    invoice_number = models.CharField(max_length=100, unique=True, blank=True, help_text="Auto-generated invoice number")
    invoice_date = models.DateField(default=timezone.now)
    due_date = models.DateField(help_text="Payment due date")
    
    # Note: status field inherited from BaseOrder, but we use invoice-specific STATUS_CHOICES
    
    # Payment terms
    payment_terms = models.CharField(max_length=20, choices=PAYMENT_TERMS, default='due_on_receipt')
    custom_terms_days = models.IntegerField(null=True, blank=True, help_text="Custom payment terms in days")
    
    # Note: customer field inherited from BaseOrder
    
    # Email tracking - Zoho-like functionality
    sent_at = models.DateTimeField(null=True, blank=True, help_text="When invoice was sent to customer")
    viewed_at = models.DateTimeField(null=True, blank=True, help_text="When customer viewed the invoice")
    last_reminder_sent = models.DateTimeField(null=True, blank=True)
    reminder_count = models.IntegerField(default=0)
    
    # Scheduled sending - Zoho feature
    is_scheduled = models.BooleanField(default=False)
    scheduled_send_date = models.DateTimeField(null=True, blank=True, help_text="Schedule invoice to be sent")
    
    # Template and customization
    template_name = models.CharField(max_length=50, choices=TEMPLATE_CHOICES, default='standard')
    
    # Notes and terms
    customer_notes = models.TextField(blank=True, default="Thanks for your business.")
    terms_and_conditions = models.TextField(blank=True)
    
    # Quotation link (if converted from quotation)
    source_quotation = models.ForeignKey('quotations.Quotation', on_delete=models.SET_NULL, null=True, blank=True, related_name='converted_invoices')
    
    # Approval workflow integration
    requires_approval = models.BooleanField(default=False)
    approval_status = models.CharField(max_length=20, default='not_required', choices=[
        ('not_required', 'Not Required'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ])
    approvals = models.ManyToManyField(Approval, related_name='invoices', blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_invoices')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    # Payment tracking (enhanced)
    payment_gateway_enabled = models.BooleanField(default=False)
    payment_gateway_name = models.CharField(max_length=50, blank=True, help_text="e.g., Stripe, M-Pesa")
    payment_link = models.URLField(max_length=500, blank=True, help_text="Payment gateway link")
    
    # Share functionality
    share_token = models.CharField(max_length=64, unique=True, blank=True, null=True, help_text="Public share token for view-only access")
    share_url = models.URLField(max_length=500, blank=True, help_text="Public share URL")
    is_shared = models.BooleanField(default=False, help_text="Whether this invoice has been shared publicly")
    shared_at = models.DateTimeField(null=True, blank=True, help_text="When invoice was first shared")
    allow_public_payment = models.BooleanField(default=False, help_text="Allow customers to pay via public share link")
    
    # Advanced features
    is_recurring = models.BooleanField(default=False)
    recurring_interval = models.CharField(max_length=20, blank=True, choices=[
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ])
    next_invoice_date = models.DateField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Invoice'
        verbose_name_plural = 'Invoices'
        ordering = ['-invoice_date', '-created_at']
        indexes = [
            models.Index(fields=['invoice_number'], name='idx_invoice_number'),
            models.Index(fields=['invoice_date'], name='idx_invoice_date'),
            models.Index(fields=['due_date'], name='idx_invoice_due_date'),
            models.Index(fields=['scheduled_send_date'], name='idx_invoice_scheduled'),
        ]
    
    def save(self, *args, **kwargs):
        # Set order_type for invoices
        if not self.order_type:
            self.order_type = 'invoice'
        
        # Auto-generate invoice number
        if not self.invoice_number:
            self.invoice_number = self.generate_invoice_number()
        
        # Auto-generate order_number if not set
        if not self.order_number:
            self.order_number = self.invoice_number
        
        # Calculate due date based on payment terms
        if not self.due_date and self.invoice_date:
            self.due_date = self.calculate_due_date()
        
        # Update balance_due
        self.balance_due = self.total - self.amount_paid
        
        # Auto-update status based on payment
        if self.amount_paid >= self.total and self.total > 0:
            self.status = 'paid'
        elif self.amount_paid > 0:
            self.status = 'partially_paid'
        elif self.due_date and self.due_date < timezone.now().date() and self.status not in ['paid', 'cancelled', 'void']:
            self.status = 'overdue'
        
        super().save(*args, **kwargs)
    
    def generate_invoice_number(self):
        """Generate unique invoice number using centralized DocumentNumberService.

        Format: PREFIX0000-DDMMYY (e.g., INV0033-150126)
        """
        business = None
        if self.branch:
            business = self.branch.business
        elif self.customer and hasattr(self.customer, 'business'):
            business = self.customer.business

        if business:
            try:
                return DocumentNumberService.generate_number(
                    business=business,
                    document_type=DocumentType.INVOICE,
                    document_date=self.invoice_date or timezone.now()
                )
            except Exception as e:
                logger.warning(f"Failed to generate invoice number via service: {e}")

        # Fallback for cases where business context is not available
        year = timezone.now().year
        count = Invoice.objects.filter(created_at__year=year).count() + 1
        date_str = timezone.now().strftime('%d%m%y')
        return f"INV{count:04d}-{date_str}"
    
    def calculate_due_date(self):
        """Calculate due date based on payment terms"""
        if self.payment_terms == 'due_on_receipt':
            return self.invoice_date
        elif self.payment_terms == 'custom' and self.custom_terms_days:
            return self.invoice_date + timezone.timedelta(days=self.custom_terms_days)
        else:
            # Extract days from terms (e.g., 'net_30' -> 30)
            days = int(self.payment_terms.split('_')[1]) if '_' in self.payment_terms else 0
            return self.invoice_date + timezone.timedelta(days=days)
    
    def mark_as_sent(self, user=None):
        """Mark invoice as sent"""
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.save(update_fields=['status', 'sent_at'])
    
    def mark_as_viewed(self):
        """Mark invoice as viewed by customer"""
        if not self.viewed_at:
            self.viewed_at = timezone.now()
            if self.status == 'sent':
                self.status = 'viewed'
            self.save(update_fields=['viewed_at', 'status'])
    
    def generate_share_token(self):
        """Generate a unique share token for public access"""
        import secrets
        if not self.share_token:
            self.share_token = secrets.token_urlsafe(32)
            self.is_shared = True
            self.shared_at = timezone.now()
            self.save(update_fields=['share_token', 'is_shared', 'shared_at'])
        return self.share_token
    
    def get_public_share_url(self, request=None):
        """Get the public share URL for this invoice"""
        if not self.share_token:
            self.generate_share_token()
        
        from django.urls import reverse
        if request:
            base_url = request.build_absolute_uri('/')
        else:
            from django.conf import settings
            base_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        
        return f"{base_url}public/invoice/{self.id}/{self.share_token}"
    
    def record_payment(self, amount, payment_method, reference=None, payment_date=None, payment_account=None):
        """Record a payment against this invoice"""
        from finance.payment.models import Payment
        # Create payment record (link to invoice via InvoicePayment relation, not a field on Payment)
        # Ensure payment_date is a timezone-aware datetime when creating Payment (Payment.payment_date is DateTimeField)
        pd = payment_date or timezone.now()
        payment = Payment.objects.create(
            payment_type='invoice_payment',
            amount=amount,
            payment_method=payment_method,
            reference_number=reference or f"PAY-{self.invoice_number}-{timezone.now().timestamp()}",
            payment_date=pd,
            customer=self.customer,
            payment_account=payment_account,
            status='completed'
        )
        
        # Persist change and then ensure invoice totals/status are consistent with stored InvoicePayments
        self.amount_paid += amount
        self.save()

        try:
            # Recalculate based on actual InvoicePayment rows to avoid mismatches
            self.recalculate_payments()
        except Exception:
            # best effort - don't fail the payment flow if recalculation has issues
            pass
        
        return payment
    
    def void_invoice(self, reason=None):
        """Void an invoice"""
        self.status = 'void'
        if reason:
            self.notes = f"{self.notes}\n\nVoided: {reason}" if self.notes else f"Voided: {reason}"
        self.save(update_fields=['status', 'notes'])
    
    def clone_invoice(self):
        """Clone this invoice (for creating similar invoices)"""
        clone = Invoice.objects.get(pk=self.pk)
        clone.pk = None
        clone.invoice_number = None  # Will auto-generate
        clone.order_number = None
        clone.status = 'draft'
        clone.sent_at = None
        clone.viewed_at = None
        clone.amount_paid = Decimal('0.00')
        clone.invoice_date = timezone.now().date()
        clone.save()
        
        # Clone line items
        for item in self.items.all():
            item.pk = None
            item.order = clone
            item.save()
        
        return clone
    
    def send_reminder(self):
        """Send payment reminder to customer"""
        self.last_reminder_sent = timezone.now()
        self.reminder_count += 1
        self.save(update_fields=['last_reminder_sent', 'reminder_count'])
        # TODO: Implement email sending logic
    
    def __str__(self):
        return f"{self.invoice_number} - {self.customer} - {self.get_status_display()}"

    def recalculate_payments(self, user=None):
        """Recalculate amount_paid, balance_due and status from InvoicePayment records.

        This ensures the invoice reflects the actual payments stored and avoids stale/partial updates.
        """
        try:
            total_paid = self.invoice_payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            old_amount = self.amount_paid
            old_balance = getattr(self, 'balance_due', None)
            old_status = self.status

            self.amount_paid = total_paid
            self.balance_due = self.total - self.amount_paid

            # Determine status
            if self.amount_paid >= self.total and self.total > 0:
                self.status = 'paid'
            elif self.amount_paid > 0:
                self.status = 'partially_paid'
            elif self.due_date and self.due_date < timezone.now().date() and self.status not in ['paid', 'cancelled', 'void']:
                self.status = 'overdue'

            # Save only if something changed
            update_fields = []
            if self.amount_paid != old_amount:
                update_fields.append('amount_paid')
            if self.balance_due != old_balance:
                update_fields.append('balance_due')
            if self.status != old_status:
                update_fields.append('status')

            if update_fields:
                # Persist and log audit trail
                self.save(update_fields=list(set(update_fields)))
                try:
                    AuditTrail.log(
                        operation=AuditTrail.UPDATE,
                        module='finance',
                        entity_type='Invoice',
                        entity_id=self.id,
                        user=user,
                        changes={f: getattr(self, f) for f in update_fields},
                        reason='Recalculated payments/status after payment change'
                    )
                except Exception:
                    # best effort; don't block
                    pass
        except Exception as e:
            # Log and re-raise if necessary
            logger = logging.getLogger(__name__)
            logger.error(f'Error recalculating payments for invoice {self.id}: {e}', exc_info=True)
            raise


class InvoicePayment(BaseModel):
    """
    Link between Invoice and Payment - Finance module integration
    Tracks all payments made against invoices
    """
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='invoice_payments')
    payment = models.ForeignKey('payment.Payment', on_delete=models.CASCADE, related_name='invoice_payments')
    amount = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    payment_account = models.ForeignKey(PaymentAccounts, on_delete=models.PROTECT)
    # Use a date (not datetime) as default to avoid DRF DateField coercion errors
    def _today():
        return timezone.now().date()

    payment_date = models.DateField(default=_today)
    notes = models.TextField(blank=True)
    
    class Meta:
        verbose_name = 'Invoice Payment'
        verbose_name_plural = 'Invoice Payments'
        ordering = ['-payment_date']
    
    def __str__(self):
        return f"{self.invoice.invoice_number} - Payment {self.amount}"


# Ensure that when an InvoicePayment is created with a payment_account we link the
# underlying Payment record to the account (this handles flows where InvoicePayment
# is created separately and the Payment wasn't created with an account). This will
# also trigger the Payment.post_save handler which creates the Transaction.
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=InvoicePayment)
def ensure_payment_has_account(sender, instance: InvoicePayment, created, **kwargs):
    try:
        payment = getattr(instance, 'payment', None)
        if not payment:
            return

        # If payment already has account, nothing to do
        if getattr(payment, 'payment_account', None):
            return

        if instance.payment_account:
            payment.payment_account = instance.payment_account
            payment.save(update_fields=['payment_account'])
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Failed to link payment account from InvoicePayment %s', getattr(instance, 'id', 'unknown'))


class InvoiceEmailLog(BaseModel):
    """Track all emails sent for invoices - Zoho-like email tracking"""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='email_logs')
    email_type = models.CharField(max_length=20, choices=[
        ('sent', 'Invoice Sent'),
        ('reminder', 'Payment Reminder'),
        ('thank_you', 'Thank You'),
        ('overdue', 'Overdue Notice'),
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
        verbose_name = 'Invoice Email Log'
        verbose_name_plural = 'Invoice Email Logs'
        ordering = ['-sent_at']
    
    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.get_email_type_display()} to {self.recipient_email}"


class CreditNote(BaseOrder):
    """
    Credit Note - Issued when invoice needs adjustment (returns, discounts, errors)
    Zoho-like feature for handling invoice corrections
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('applied', 'Applied'),
        ('void', 'Void'),
    ]
    
    # Credit Note identifiers
    credit_note_number = models.CharField(max_length=100, unique=True, blank=True)
    credit_note_date = models.DateField(default=timezone.now)
    
    # Link to original invoice
    source_invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='credit_notes')
    
    # Note: customer, status, and notes fields inherited from BaseOrder
    
    # Reason for credit note
    reason = models.TextField(help_text="Reason for issuing credit note")
    
    class Meta:
        verbose_name = 'Credit Note'
        verbose_name_plural = 'Credit Notes'
        ordering = ['-credit_note_date', '-created_at']
        indexes = [
            models.Index(fields=['credit_note_number'], name='idx_credit_note_number'),
            models.Index(fields=['source_invoice'], name='idx_credit_note_invoice'),
            models.Index(fields=['credit_note_date'], name='idx_credit_note_date'),
        ]
    
    def save(self, *args, **kwargs):
        # Set order_type
        if not self.order_type:
            self.order_type = 'credit_note'
        
        # Auto-generate credit note number
        if not self.credit_note_number:
            self.credit_note_number = self.generate_credit_note_number()
        
        # Auto-generate order_number if not set
        if not self.order_number:
            self.order_number = self.credit_note_number
        
        super().save(*args, **kwargs)
        
        # Update invoice when credit note is applied
        if self.status == 'applied':
            self.apply_to_invoice()
    
    def generate_credit_note_number(self):
        """Generate unique credit note number using centralized DocumentNumberService.

        Format: PREFIX0000-DDMMYY (e.g., CRN0001-150126)
        """
        business = None
        if self.branch:
            business = self.branch.business
        elif self.source_invoice and self.source_invoice.branch:
            business = self.source_invoice.branch.business

        if business:
            try:
                return DocumentNumberService.generate_number(
                    business=business,
                    document_type=DocumentType.CREDIT_NOTE,
                    document_date=self.credit_note_date or timezone.now()
                )
            except Exception as e:
                logger.warning(f"Failed to generate credit note number via service: {e}")

        # Fallback
        year = timezone.now().year
        count = CreditNote.objects.filter(created_at__year=year).count() + 1
        date_str = timezone.now().strftime('%d%m%y')
        return f"CRN{count:04d}-{date_str}"
    
    def apply_to_invoice(self):
        """Apply credit note to reduce invoice balance"""
        if self.source_invoice:
            # Reduce invoice amount_paid is counter-intuitive, so we track it separately
            # This is just for record keeping
            pass
    
    def __str__(self):
        return f"{self.credit_note_number} - {self.source_invoice.invoice_number} - {self.get_status_display()}"

    @classmethod
    def create_from_invoice(cls, invoice, reason, items=None, created_by=None):
        """Create a credit note from an existing invoice.

        Args:
            invoice: The source Invoice instance
            reason: Reason for creating the credit note
            items: Optional list of items to include (defaults to all invoice items)
            created_by: User creating the credit note

        Returns:
            CreditNote: The newly created credit note
        """
        credit_note = cls(
            source_invoice=invoice,
            customer=invoice.customer,
            branch=invoice.branch,
            reason=reason,
            created_by=created_by,
            subtotal=invoice.subtotal,
            tax_amount=invoice.tax_amount,
            discount_amount=invoice.discount_amount,
            shipping_cost=invoice.shipping_cost,
            total=invoice.total,
            tax_mode=invoice.tax_mode,
            tax_rate=invoice.tax_rate,
            notes=invoice.notes,
            status='draft'
        )
        credit_note.save()

        # Clone items from invoice
        from core_orders.models import OrderItem
        source_items = items if items else invoice.items.all()
        for item in source_items:
            OrderItem.objects.create(
                order=credit_note,
                content_type=item.content_type,
                object_id=item.object_id,
                name=item.name,
                description=item.description,
                sku=item.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                notes=item.notes
            )

        return credit_note


class DebitNote(BaseOrder):
    """
    Debit Note - Issued to increase invoice amount (additional charges discovered)
    Zoho-like feature for handling invoice adjustments
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('applied', 'Applied'),
        ('void', 'Void'),
    ]

    # Debit Note identifiers
    debit_note_number = models.CharField(max_length=100, unique=True, blank=True)
    debit_note_date = models.DateField(default=timezone.now)

    # Link to original invoice
    source_invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='debit_notes')

    # Note: customer, status, and notes fields inherited from BaseOrder

    # Reason for debit note
    reason = models.TextField(help_text="Reason for issuing debit note")

    class Meta:
        verbose_name = 'Debit Note'
        verbose_name_plural = 'Debit Notes'
        ordering = ['-debit_note_date', '-created_at']
        indexes = [
            models.Index(fields=['debit_note_number'], name='idx_debit_note_number'),
            models.Index(fields=['source_invoice'], name='idx_debit_note_invoice'),
            models.Index(fields=['debit_note_date'], name='idx_debit_note_date'),
        ]

    def save(self, *args, **kwargs):
        # Set order_type
        if not self.order_type:
            self.order_type = 'debit_note'

        # Auto-generate debit note number
        if not self.debit_note_number:
            self.debit_note_number = self.generate_debit_note_number()

        # Auto-generate order_number if not set
        if not self.order_number:
            self.order_number = self.debit_note_number

        super().save(*args, **kwargs)

    def generate_debit_note_number(self):
        """Generate unique debit note number using centralized DocumentNumberService.

        Format: PREFIX0000-DDMMYY (e.g., DBN0001-150126)
        """
        business = None
        if self.branch:
            business = self.branch.business
        elif self.source_invoice and self.source_invoice.branch:
            business = self.source_invoice.branch.business

        if business:
            try:
                return DocumentNumberService.generate_number(
                    business=business,
                    document_type=DocumentType.DEBIT_NOTE,
                    document_date=self.debit_note_date or timezone.now()
                )
            except Exception as e:
                logger.warning(f"Failed to generate debit note number via service: {e}")

        # Fallback
        year = timezone.now().year
        count = DebitNote.objects.filter(created_at__year=year).count() + 1
        date_str = timezone.now().strftime('%d%m%y')
        return f"DBN{count:04d}-{date_str}"

    def __str__(self):
        return f"{self.debit_note_number} - {self.source_invoice.invoice_number} - {self.get_status_display()}"

    @classmethod
    def create_from_invoice(cls, invoice, reason, items=None, created_by=None):
        """Create a debit note from an existing invoice.

        Args:
            invoice: The source Invoice instance
            reason: Reason for creating the debit note
            items: Optional list of items to include (defaults to all invoice items)
            created_by: User creating the debit note

        Returns:
            DebitNote: The newly created debit note
        """
        debit_note = cls(
            source_invoice=invoice,
            customer=invoice.customer,
            branch=invoice.branch,
            reason=reason,
            created_by=created_by,
            subtotal=invoice.subtotal,
            tax_amount=invoice.tax_amount,
            discount_amount=invoice.discount_amount,
            shipping_cost=invoice.shipping_cost,
            total=invoice.total,
            tax_mode=invoice.tax_mode,
            tax_rate=invoice.tax_rate,
            notes=invoice.notes,
            status='draft'
        )
        debit_note.save()

        # Clone items from invoice
        from core_orders.models import OrderItem
        source_items = items if items else invoice.items.all()
        for item in source_items:
            OrderItem.objects.create(
                order=debit_note,
                content_type=item.content_type,
                object_id=item.object_id,
                name=item.name,
                description=item.description,
                sku=item.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                notes=item.notes
            )

        return debit_note


class DeliveryNote(BaseOrder):
    """
    Delivery Note - Document confirming delivery of goods to customer.
    Can be created from Invoice or independently.
    Reuses PDF generation with document_type='delivery_note'.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Delivery'),
        ('in_transit', 'In Transit'),
        ('delivered', 'Delivered'),
        ('partially_delivered', 'Partially Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    # Delivery Note identifiers
    delivery_note_number = models.CharField(max_length=100, unique=True, blank=True)
    delivery_date = models.DateField(default=timezone.now)

    # Link to source document (Invoice or Purchase Order)
    source_invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='dn_from_invoice',
        help_text="Source invoice for this delivery note"
    )
    source_purchase_order = models.ForeignKey(
        'orders.PurchaseOrder', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='dn_from_po',
        help_text="Source purchase order for this delivery note"
    )

    # Delivery details
    delivery_address = models.TextField(blank=True, help_text="Delivery address")
    driver_name = models.CharField(max_length=100, blank=True, help_text="Driver/courier name")
    driver_phone = models.CharField(max_length=20, blank=True, help_text="Driver contact number")
    vehicle_number = models.CharField(max_length=50, blank=True, help_text="Vehicle registration number")

    # Recipient details
    received_by = models.CharField(max_length=100, blank=True, help_text="Name of person who received goods")
    received_at = models.DateTimeField(null=True, blank=True, help_text="When goods were received")
    receiver_signature = models.ImageField(upload_to='delivery_signatures/', null=True, blank=True)

    # Special instructions
    special_instructions = models.TextField(blank=True, help_text="Special delivery instructions")

    class Meta:
        verbose_name = 'Delivery Note'
        verbose_name_plural = 'Delivery Notes'
        ordering = ['-delivery_date', '-created_at']
        indexes = [
            models.Index(fields=['delivery_note_number'], name='idx_delivery_note_number'),
            models.Index(fields=['source_invoice'], name='idx_dn_src_invoice'),
            models.Index(fields=['delivery_date'], name='idx_delivery_note_date'),
        ]

    def save(self, *args, **kwargs):
        # Set order_type
        if not self.order_type:
            self.order_type = 'delivery_note'

        # Auto-generate delivery note number
        if not self.delivery_note_number:
            self.delivery_note_number = self.generate_delivery_note_number()

        # Auto-generate order_number if not set
        if not self.order_number:
            self.order_number = self.delivery_note_number

        super().save(*args, **kwargs)

    def generate_delivery_note_number(self):
        """Generate unique delivery note number using centralized DocumentNumberService.

        Format: PREFIX0000-DDMMYY (e.g., POD0001-150126)
        """
        business = None
        if self.branch:
            business = self.branch.business
        elif self.source_invoice and self.source_invoice.branch:
            business = self.source_invoice.branch.business

        if business:
            try:
                return DocumentNumberService.generate_number(
                    business=business,
                    document_type=DocumentType.DELIVERY_NOTE,
                    document_date=self.delivery_date or timezone.now()
                )
            except Exception as e:
                logger.warning(f"Failed to generate delivery note number via service: {e}")

        # Fallback
        year = timezone.now().year
        count = DeliveryNote.objects.filter(created_at__year=year).count() + 1
        date_str = timezone.now().strftime('%d%m%y')
        return f"POD{count:04d}-{date_str}"

    def mark_delivered(self, received_by=None, notes=None):
        """Mark delivery note as delivered."""
        self.status = 'delivered'
        self.received_at = timezone.now()
        if received_by:
            self.received_by = received_by
        if notes:
            self.notes = f"{self.notes}\n\nDelivery notes: {notes}" if self.notes else f"Delivery notes: {notes}"
        self.save(update_fields=['status', 'received_at', 'received_by', 'notes'])

    @classmethod
    def create_from_invoice(cls, invoice, created_by=None, delivery_address=None):
        """Create a delivery note from an existing invoice.

        Args:
            invoice: The source Invoice instance
            created_by: User creating the delivery note
            delivery_address: Optional delivery address (defaults to invoice shipping_address)

        Returns:
            DeliveryNote: The newly created delivery note
        """
        delivery_note = cls(
            source_invoice=invoice,
            customer=invoice.customer,
            branch=invoice.branch,
            created_by=created_by,
            delivery_address=delivery_address or invoice.shipping_address or '',
            subtotal=invoice.subtotal,
            tax_amount=invoice.tax_amount,
            discount_amount=invoice.discount_amount,
            shipping_cost=invoice.shipping_cost,
            total=invoice.total,
            tax_mode=invoice.tax_mode,
            tax_rate=invoice.tax_rate,
            notes=invoice.notes,
            status='draft'
        )
        delivery_note.save()

        # Clone items from invoice
        from core_orders.models import OrderItem
        for item in invoice.items.all():
            OrderItem.objects.create(
                order=delivery_note,
                content_type=item.content_type,
                object_id=item.object_id,
                name=item.name,
                description=item.description,
                sku=item.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                notes=item.notes
            )

        return delivery_note

    @classmethod
    def create_from_purchase_order(cls, purchase_order, created_by=None, delivery_address=None):
        """Create a delivery note from an existing purchase order.

        Args:
            purchase_order: The source PurchaseOrder instance
            created_by: User creating the delivery note
            delivery_address: Optional delivery address

        Returns:
            DeliveryNote: The newly created delivery note
        """
        delivery_note = cls(
            source_purchase_order=purchase_order,
            supplier=purchase_order.supplier,
            branch=purchase_order.branch,
            created_by=created_by,
            delivery_address=delivery_address or getattr(purchase_order, 'delivery_address', '') or '',
            subtotal=purchase_order.subtotal,
            tax_amount=purchase_order.tax_amount,
            discount_amount=purchase_order.discount_amount,
            shipping_cost=purchase_order.shipping_cost,
            total=purchase_order.total,
            tax_mode=getattr(purchase_order, 'tax_mode', 'per_item'),
            tax_rate=getattr(purchase_order, 'tax_rate', Decimal('0')),
            notes=purchase_order.notes,
            status='draft'
        )
        delivery_note.save()

        # Clone items from purchase order
        from core_orders.models import OrderItem
        for item in purchase_order.items.all():
            OrderItem.objects.create(
                order=delivery_note,
                content_type=item.content_type,
                object_id=item.object_id,
                name=item.name,
                description=item.description,
                sku=item.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                notes=item.notes
            )

        return delivery_note

    def __str__(self):
        source = ""
        if self.source_invoice:
            source = f" (from {self.source_invoice.invoice_number})"
        elif self.source_purchase_order:
            source = f" (from {self.source_purchase_order.order_number})"
        return f"{self.delivery_note_number}{source} - {self.get_status_display()}"

class ProformaInvoice(BaseOrder):
    """
    Proforma Invoice - Preliminary invoice sent before goods/services are delivered.
    Used for quotations that need to look like invoices, customs, or advance payment requests.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('accepted', 'Accepted'),
        ('converted', 'Converted to Invoice'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]

    # Proforma Invoice identifiers
    proforma_number = models.CharField(max_length=100, unique=True, blank=True)
    proforma_date = models.DateField(default=timezone.now)
    valid_until = models.DateField(null=True, blank=True, help_text="Proforma validity date")

    # Link to source quotation
    source_quotation = models.ForeignKey(
        'quotations.Quotation', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='proforma_invoices',
        help_text="Source quotation for this proforma"
    )

    # Converted invoice link
    converted_invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='source_proformas',
        help_text="Invoice created from this proforma"
    )

    # Notes specific to proforma
    customer_notes = models.TextField(blank=True, default="This is a proforma invoice and not a demand for payment.")
    terms_and_conditions = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Proforma Invoice'
        verbose_name_plural = 'Proforma Invoices'
        ordering = ['-proforma_date', '-created_at']
        indexes = [
            models.Index(fields=['proforma_number'], name='idx_proforma_number'),
            models.Index(fields=['proforma_date'], name='idx_proforma_date'),
            models.Index(fields=['valid_until'], name='idx_proforma_valid_until'),
        ]

    def save(self, *args, **kwargs):
        # Set order_type
        if not self.order_type:
            self.order_type = 'proforma'

        # Auto-generate proforma number
        if not self.proforma_number:
            self.proforma_number = self.generate_proforma_number()

        # Auto-generate order_number if not set
        if not self.order_number:
            self.order_number = self.proforma_number

        super().save(*args, **kwargs)

    def generate_proforma_number(self):
        """Generate unique proforma invoice number.

        Format: PREFIX0000-DDMMYY (e.g., PFI0001-150126)
        """
        business = None
        if self.branch:
            business = self.branch.business
        elif self.source_quotation and self.source_quotation.branch:
            business = self.source_quotation.branch.business

        if business:
            try:
                # Use quotation type since proforma is similar
                return DocumentNumberService.generate_number(
                    business=business,
                    document_type=DocumentType.QUOTATION,
                    document_date=self.proforma_date or timezone.now()
                ).replace('QOT', 'PFI')
            except Exception as e:
                logger.warning(f"Failed to generate proforma number via service: {e}")

        # Fallback
        year = timezone.now().year
        count = ProformaInvoice.objects.filter(created_at__year=year).count() + 1
        date_str = timezone.now().strftime('%d%m%y')
        return f"PFI{count:04d}-{date_str}"

    def convert_to_invoice(self, created_by=None):
        """Convert this proforma invoice to a real invoice.

        Returns:
            Invoice: The newly created invoice
        """
        if self.converted_invoice:
            return self.converted_invoice

        invoice = Invoice(
            customer=self.customer,
            branch=self.branch,
            created_by=created_by or self.created_by,
            subtotal=self.subtotal,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            shipping_cost=self.shipping_cost,
            total=self.total,
            tax_mode=self.tax_mode,
            tax_rate=self.tax_rate,
            customer_notes=self.customer_notes,
            terms_and_conditions=self.terms_and_conditions,
            notes=f"Converted from Proforma {self.proforma_number}",
            status='draft',
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
        )
        invoice.save()

        # Clone items
        from core_orders.models import OrderItem
        for item in self.items.all():
            OrderItem.objects.create(
                order=invoice,
                content_type=item.content_type,
                object_id=item.object_id,
                name=item.name,
                description=item.description,
                sku=item.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                notes=item.notes
            )

        # Update proforma status
        self.status = 'converted'
        self.converted_invoice = invoice
        self.save(update_fields=['status', 'converted_invoice'])

        return invoice

    @classmethod
    def create_from_quotation(cls, quotation, created_by=None):
        """Create a proforma invoice from an existing quotation.

        Args:
            quotation: The source Quotation instance
            created_by: User creating the proforma

        Returns:
            ProformaInvoice: The newly created proforma invoice
        """
        proforma = cls(
            source_quotation=quotation,
            customer=quotation.customer,
            branch=quotation.branch,
            created_by=created_by or quotation.created_by,
            valid_until=quotation.valid_until,
            subtotal=quotation.subtotal,
            tax_amount=quotation.tax_amount,
            discount_amount=quotation.discount_amount,
            shipping_cost=quotation.shipping_cost,
            total=quotation.total,
            tax_mode=quotation.tax_mode,
            tax_rate=quotation.tax_rate,
            customer_notes=getattr(quotation, 'customer_notes', ''),
            terms_and_conditions=getattr(quotation, 'terms_and_conditions', ''),
            notes=f"Created from Quotation {quotation.quotation_number}",
            shipping_address=quotation.shipping_address,
            billing_address=quotation.billing_address,
            status='draft'
        )
        proforma.save()

        # Clone items from quotation
        from core_orders.models import OrderItem
        for item in quotation.items.all():
            OrderItem.objects.create(
                order=proforma,
                content_type=item.content_type,
                object_id=item.object_id,
                name=item.name,
                description=item.description,
                sku=item.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                notes=item.notes
            )

        return proforma

    def __str__(self):
        return f"{self.proforma_number} - {self.customer} - {self.get_status_display()}"
