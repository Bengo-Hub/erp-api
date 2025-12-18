from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils import timezone
from crm.contacts.models import Contact
from business.models import Branch, PickupStations
from addresses.models import AddressBook
from decimal import Decimal

User = get_user_model()


class BaseOrder(models.Model):
    """
    Centralized Base Order Model - Standard ERP Order Structure
    Serves as the foundation for all order types across the system
    """
    ORDER_STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("processing", "Processing"),
        ("packed", "Packed"),
        ("shipped", "Shipped"),
        ("in_transit", "In Transit"),
        ("out_for_delivery", "Out for Delivery"),
        ("delivered", "Delivered"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("on_hold", "On Hold"),
        ("backordered", "Backordered"),
        ("refund_requested", "Refund Requested"),
        ("refunded", "Refunded"),
        ("payment_failed", "Payment Failed"),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("partial", "Partial"),
        ("paid", "Paid"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
        ("partially_refunded", "Partially Refunded"),
        ("awaiting_confirmation", "Awaiting Confirmation"),
        ("processing", "Processing"),
        ("authorized", "Authorized"),
    ]
    
    SOURCE_CHOICES = [
        ("online", "Online Store"),
        ("pos", "Point of Sale"),
        ("manual", "Manual Entry"),
        ("mobile_app", "Mobile App"),
        ("procurement", "Procurement"),
        ("other", "Other"),
    ]
    
    DELIVERY_TYPE_CHOICES = [
        ("home", "Home Delivery"),
        ("pickup", "Pickup Station"),
        ("office", "Office Delivery"),
        ("self_pickup", "Self Pickup"),
    ]
    
    # Core Order Information
    order_number = models.CharField(max_length=50, unique=True, blank=True)
    reference_id = models.CharField(max_length=100, blank=True, null=True)
    order_type = models.CharField(max_length=50, help_text="Type of order (ecommerce, procurement, etc.)")
    
    # Parties
    customer = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    supplier = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='supplier_orders', null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_orders')
    
    # Source and Type
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    delivery_type = models.CharField(max_length=20, choices=DELIVERY_TYPE_CHOICES, default='home')
    
    # Financial Details
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    # Tax mode controls whether taxes are applied per-line (default) or on the final/subtotal amount
    TAX_MODE_CHOICES = [
        ('line_items', 'Per Line Items'),
        ('on_total', 'On Final Amount')
    ]
    tax_mode = models.CharField(max_length=20, choices=TAX_MODE_CHOICES, default='line_items')
    # Percentage applied when tax_mode == 'on_total'
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text='Tax percentage applied to subtotal when tax_mode is on_total')
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    shipping_cost = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    balance_due = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Status Management
    status = models.CharField(max_length=50, choices=ORDER_STATUS_CHOICES, default='draft')
    payment_status = models.CharField(max_length=50, choices=PAYMENT_STATUS_CHOICES, default='pending')
    fulfillment_status = models.CharField(max_length=50, blank=True, null=True)
    
    # Delivery Information
    pickup_station = models.ForeignKey(PickupStations, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    shipping_address = models.ForeignKey(AddressBook, on_delete=models.SET_NULL, null=True, blank=True, related_name='shipping_orders')
    billing_address = models.ForeignKey(AddressBook, on_delete=models.SET_NULL, null=True, blank=True, related_name='billing_orders')
    
    # Shipping and Tracking
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    shipping_provider = models.CharField(max_length=100, blank=True, null=True)
    estimated_delivery_date = models.DateField(blank=True, null=True)
    actual_delivery_date = models.DateTimeField(blank=True, null=True)
    delivery_notes = models.TextField(blank=True, null=True)
    
    # Terms and Conditions
    terms = models.TextField(blank=True, help_text="Order terms and conditions")
    notes = models.TextField(blank=True, null=True)
    
    # Order Lifecycle Timestamps
    order_date = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(blank=True, null=True)
    processing_at = models.DateTimeField(blank=True, null=True)
    packed_at = models.DateTimeField(blank=True, null=True)
    shipped_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    
    # KRA Compliance (Kenyan Market)
    kra_compliance = models.BooleanField(default=False, help_text="Whether order complies with KRA requirements")
    tax_reference = models.CharField(max_length=100, blank=True, null=True, help_text="KRA tax reference number")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'orders'
        ordering = ['-order_date']
        verbose_name = 'Order'
        verbose_name_plural = 'Orders'
        indexes = [
            models.Index(fields=['order_number'], name='idx_order_number'),
            models.Index(fields=['order_type'], name='idx_order_type'),
            models.Index(fields=['status'], name='idx_order_status'),
            models.Index(fields=['payment_status'], name='idx_order_payment_status'),
            models.Index(fields=['customer'], name='idx_order_customer'),
            models.Index(fields=['supplier'], name='idx_order_supplier'),
            models.Index(fields=['order_date'], name='idx_order_date'),
            models.Index(fields=['source'], name='idx_order_source'),
            models.Index(fields=['delivery_type'], name='idx_order_delivery_type'),
            models.Index(fields=['kra_compliance'], name='idx_order_kra_compliance'),
        ]

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        super().save(*args, **kwargs)

    def generate_order_number(self):
        """Generate unique order number based on type"""
        prefix = self.order_type.upper()[:2] if self.order_type else "OR"
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        return f"{prefix}-{timestamp}"

    def __str__(self):
        return f"{self.order_number} - {self.order_type}"

    # Order Lifecycle Methods
    def confirm_order(self):
        """Confirm the order"""
        if self.status == 'pending':
            self.status = 'confirmed'
            self.confirmed_at = timezone.now()
            self.save()

    def process_order(self):
        """Start processing the order"""
        if self.status == 'confirmed':
            self.status = 'processing'
            self.processing_at = timezone.now()
            self.save()

    def pack_order(self):
        """Mark order as packed"""
        if self.status == 'processing':
            self.status = 'packed'
            self.packed_at = timezone.now()
            self.save()

    def ship_order(self):
        """Mark order as shipped"""
        if self.status == 'packed':
            self.status = 'shipped'
            self.shipped_at = timezone.now()
            self.save()

    def deliver_order(self):
        """Mark order as delivered"""
        if self.status in ['shipped', 'out_for_delivery']:
            self.status = 'delivered'
            self.delivered_at = timezone.now()
            self.save()

    def cancel_order(self, reason=None):
        """Cancel the order"""
        if self.status not in ['delivered', 'completed', 'cancelled']:
            self.status = 'cancelled'
            self.cancelled_at = timezone.now()
            if reason:
                self.notes = f"Cancelled: {reason}"
            self.save()

    # Properties
    @property
    def is_paid(self):
        """Check if order is fully paid"""
        return self.payment_status == 'paid'

    @property
    def is_delivered(self):
        """Check if order is delivered"""
        return self.status == 'delivered'

    @property
    def is_cancelled(self):
        """Check if order is cancelled"""
        return self.status == 'cancelled'

    @property
    def can_be_cancelled(self):
        """Check if order can be cancelled"""
        return self.status not in ['delivered', 'completed', 'cancelled']

    @property
    def delivery_address_display(self):
        """Get formatted delivery address"""
        if self.shipping_address:
            return self.shipping_address.full_address
        return "No delivery address specified"


class OrderItem(models.Model):
    """
    Order Items - Generic items that can be linked to any order type
    """
    order = models.ForeignKey(BaseOrder, on_delete=models.CASCADE, related_name='items')
    
    # Generic content type for different item types
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Item details
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    sku = models.CharField(max_length=100, blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    total_price = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Additional fields
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'order_items'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['order'], name='idx_order_item_order'),
            models.Index(fields=['content_type', 'object_id'], name='idx_order_item_content'),
            models.Index(fields=['sku'], name='idx_order_item_sku'),
        ]

    def save(self, *args, **kwargs):
        if not self.total_price:
            self.total_price = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order.order_number} - {self.name}"


class OrderPayment(models.Model):
    """
    Order Payment - Links orders to payments
    """
    order = models.ForeignKey(BaseOrder, on_delete=models.CASCADE, related_name='payments')
    payment = models.ForeignKey('payment.Payment', on_delete=models.CASCADE, related_name='order_payments')
    
    # Additional order-specific payment fields
    amount_applied = models.DecimalField(max_digits=15, decimal_places=2, help_text="Amount applied to this specific order")
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'order_payments'
        unique_together = ['order', 'payment']
        indexes = [
            models.Index(fields=['order'], name='idx_order_payment_order'),
            models.Index(fields=['payment'], name='idx_order_payment_payment'),
        ]

    def __str__(self):
        return f"{self.order.order_number} - {self.payment.reference_number}"

    # Properties to access payment details
    @property
    def amount(self):
        return self.payment.amount

    @property
    def payment_method(self):
        return self.payment.payment_method

    @property
    def status(self):
        return self.payment.status

    @property
    def transaction_id(self):
        return self.payment.transaction_id
