from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.contrib.auth import get_user_model
from decimal import Decimal
from core.models import BaseModel
from core_orders.models import BaseOrder
from crm.contacts.models import Contact
from business.models import Branch, Bussiness
import uuid

User = get_user_model()


class Quotation(BaseOrder):
    """
    Quotation/Quote Model - Sales quotations that can be converted to invoices
    Extends BaseOrder for line items and financial tracking
    Part of the sales workflow: Quote -> Invoice -> Payment
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('viewed', 'Viewed'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
        ('converted', 'Converted to Invoice'),
        ('cancelled', 'Cancelled'),
    ]
    
    VALIDITY_PERIODS = [
        ('7_days', '7 Days'),
        ('15_days', '15 Days'),
        ('30_days', '30 Days'),
        ('60_days', '60 Days'),
        ('90_days', '90 Days'),
        ('custom', 'Custom'),
    ]
    
    # Quotation specific identifiers
    quotation_number = models.CharField(max_length=100, unique=True, blank=True, help_text="Auto-generated quotation number")
    quotation_date = models.DateField(default=timezone.now)
    valid_until = models.DateField(help_text="Quotation expiry date")
    
    # RFQ and Tender reference fields
    rfq_number = models.CharField(max_length=100, blank=True, null=True, help_text="RFQ (Request for Quotation) reference number")
    tender_quotation_ref = models.CharField(max_length=100, blank=True, null=True, help_text="Tender/Quotation reference number")
    
    # Note: status field inherited from BaseOrder, but we use quotation-specific STATUS_CHOICES
    
    # Validity
    validity_period = models.CharField(max_length=20, choices=VALIDITY_PERIODS, default='30_days')
    custom_validity_days = models.IntegerField(null=True, blank=True, help_text="Custom validity in days")
    
    # Note: customer field inherited from BaseOrder
    
    # Tracking
    sent_at = models.DateTimeField(null=True, blank=True, help_text="When quotation was sent to customer")
    viewed_at = models.DateTimeField(null=True, blank=True, help_text="When customer viewed the quotation")
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    
    # Notes
    introduction = models.TextField(blank=True, help_text="Introduction text for the quotation")
    customer_notes = models.TextField(blank=True, default="Thank you for considering our services.")
    terms_and_conditions = models.TextField(blank=True)
    
    # Conversion tracking
    is_converted = models.BooleanField(default=False)
    converted_at = models.DateTimeField(null=True, blank=True)
    converted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='converted_quotations')
    
    # Discount and special terms
    discount_type = models.CharField(max_length=20, choices=[
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
    ], default='percentage')
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Follow-up reminders
    follow_up_date = models.DateField(null=True, blank=True)
    reminder_sent = models.BooleanField(default=False)
    
    # Sharing & Public Access
    share_token = models.CharField(max_length=255, unique=True, null=True, blank=True, help_text="Unique token for public share link")
    is_shared = models.BooleanField(default=False, help_text="Whether this quotation has been shared publicly")
    shared_at = models.DateTimeField(null=True, blank=True, help_text="When the quotation was first shared")
    allow_public_payment = models.BooleanField(default=False, help_text="Allow customer to make payment via public link")
    
    class Meta:
        verbose_name = 'Quotation'
        verbose_name_plural = 'Quotations'
        ordering = ['-quotation_date', '-created_at']
        indexes = [
            models.Index(fields=['quotation_number'], name='idx_quotation_number'),
            models.Index(fields=['quotation_date'], name='idx_quotation_date'),
            models.Index(fields=['valid_until'], name='idx_quotation_valid_until'),
            models.Index(fields=['is_converted'], name='idx_quotation_converted'),
        ]
    
    def save(self, *args, **kwargs):
        # Set order_type for quotations
        if not self.order_type:
            self.order_type = 'quotation'
        
        # Auto-generate quotation number
        if not self.quotation_number:
            self.quotation_number = self.generate_quotation_number()
        
        # Auto-generate order_number if not set
        if not self.order_number:
            self.order_number = self.quotation_number
        
        # Calculate valid_until based on validity period
        if not self.valid_until and self.quotation_date:
            self.valid_until = self.calculate_valid_until()
        
        # Auto-update status if expired
        if self.valid_until and self.valid_until < timezone.now().date() and self.status not in ['accepted', 'declined', 'converted', 'cancelled']:
            self.status = 'expired'
        
        super().save(*args, **kwargs)
    
    def generate_quotation_number(self):
        """Generate unique quotation number: QUOT-YYYY-NNNNNN"""
        year = timezone.now().year
        count = Quotation.objects.filter(created_at__year=year).count() + 1
        return f"QUOT-{year}-{count:06d}"
    
    def calculate_valid_until(self):
        """Calculate expiry date based on validity period"""
        if self.validity_period == 'custom' and self.custom_validity_days:
            days = self.custom_validity_days
        else:
            # Extract days from period (e.g., '30_days' -> 30)
            days = int(self.validity_period.split('_')[0]) if '_' in self.validity_period else 30
        
        return self.quotation_date + timezone.timedelta(days=days)
    
    def mark_as_sent(self, user=None):
        """Mark quotation as sent"""
        self.status = 'sent'
        self.sent_at = timezone.now()
        if user:
            self.updated_by = user
        self.save(update_fields=['status', 'sent_at', 'updated_by'])
    
    def mark_as_viewed(self):
        """Mark quotation as viewed by customer"""
        if not self.viewed_at:
            self.viewed_at = timezone.now()
            if self.status == 'sent':
                self.status = 'viewed'
            self.save(update_fields=['viewed_at', 'status'])
    
    def mark_as_accepted(self, user=None):
        """Mark quotation as accepted by customer"""
        self.status = 'accepted'
        self.accepted_at = timezone.now()
        if user:
            self.updated_by = user
        self.save(update_fields=['status', 'accepted_at', 'updated_by'])
    
    def mark_as_declined(self, reason=None):
        """Mark quotation as declined"""
        self.status = 'declined'
        self.declined_at = timezone.now()
        if reason:
            self.notes = f"{self.notes}\n\nDeclined: {reason}" if self.notes else f"Declined: {reason}"
        self.save(update_fields=['status', 'declined_at', 'notes'])
    
    def convert_to_invoice(self, user=None):
        """
        Convert this quotation to an invoice
        This is a key feature for sales workflow
        """
        from finance.invoicing.models import Invoice
        
        if self.is_converted:
            raise ValueError("This quotation has already been converted to an invoice")
        
        if self.status == 'expired':
            raise ValueError("Cannot convert an expired quotation")
        
        # Create invoice from quotation
        invoice = Invoice.objects.create(
            # Copy customer and branch
            customer=self.customer,
            branch=self.branch,
            created_by=user or self.created_by,
            
            # Copy financial details
            subtotal=self.subtotal,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            shipping_cost=self.shipping_cost,
            total=self.total,
            
            # Link to quotation (invoice.source_quotation)
            source_quotation=self,
            
            # Copy delivery info
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            delivery_type=self.delivery_type,
            
            # Copy notes
            customer_notes=self.customer_notes,
            terms_and_conditions=self.terms_and_conditions,
            
            # Set invoice date and due date
            invoice_date=timezone.now().date(),
            payment_terms='net_30',  # Default, can be customized
        )
        
        # Clone line items
        for item in self.items.all():
            item.pk = None
            item.order = invoice
            item.save()
        
        # Mark quotation as converted
        self.is_converted = True
        self.status = 'converted'
        self.converted_at = timezone.now()
        self.converted_by = user
        self.save(update_fields=['is_converted', 'status', 'converted_at', 'converted_by'])
        
        return invoice
    
    def clone_quotation(self):
        """Clone this quotation (for creating similar quotes)"""
        clone = Quotation.objects.get(pk=self.pk)
        clone.pk = None
        clone.quotation_number = None  # Will auto-generate
        clone.order_number = None
        clone.status = 'draft'
        clone.sent_at = None
        clone.viewed_at = None
        clone.accepted_at = None
        clone.declined_at = None
        clone.is_converted = False
        clone.quotation_date = timezone.now().date()
        clone.valid_until = None  # Will auto-calculate
        clone.save()
        
        # Clone line items
        for item in self.items.all():
            item.pk = None
            item.order = clone
            item.save()
        
        return clone
    
    def send_follow_up_reminder(self):
        """Send follow-up reminder to customer"""
        self.reminder_sent = True
        self.save(update_fields=['reminder_sent'])
        # TODO: Implement email sending logic
    
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
        """Get the public share URL for this quotation"""
        if not self.share_token:
            self.generate_share_token()
        
        from django.urls import reverse
        if request:
            base_url = request.build_absolute_uri('/')
        else:
            from django.conf import settings
            base_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        
        return f"{base_url}public/quotation/{self.id}/{self.share_token}"
    
    def __str__(self):
        return f"{self.quotation_number} - {self.customer} - {self.get_status_display()}"


class QuotationEmailLog(BaseModel):
    """Track all emails sent for quotations"""
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='email_logs')
    email_type = models.CharField(max_length=20, choices=[
        ('sent', 'Quotation Sent'),
        ('reminder', 'Follow-up Reminder'),
        ('thank_you', 'Thank You'),
        ('expired_notice', 'Expiry Notice'),
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
        verbose_name = 'Quotation Email Log'
        verbose_name_plural = 'Quotation Email Logs'
        ordering = ['-sent_at']
    
    def __str__(self):
        return f"{self.quotation.quotation_number} - {self.get_email_type_display()} to {self.recipient_email}"
