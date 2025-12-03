from django.db import models
from procurement.purchases.models import *
from procurement.requisitions.models import *
from crm.contacts.models import *
from core.models import Departments
from core_orders.models import BaseOrder
from approvals.models import Approval
from procurement.orders.functions import generate_purchase_order
from procurement.requisitions.models import ProcurementRequest
from django.utils import timezone
from django.core.exceptions import ValidationError
import logging

from django.contrib.auth import get_user_model
User = get_user_model()

logger = logging.getLogger(__name__)

# Create your models here.


class PurchaseOrder(BaseOrder):
    """
    Procurement Purchase Order - Uses unified order structure
    Extends the base order concept for procurement-specific functionality
    """
    # Procurement specific fields only (remove duplicates from BaseOrder)
    requisition = models.OneToOneField('requisitions.ProcurementRequest', on_delete=models.PROTECT, related_name='purchase_order')
    
    # Procurement specific financial fields
    approved_budget = models.DecimalField(max_digits=15, decimal_places=2, help_text="Approved budget for this purchase")
    actual_cost = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, help_text="Actual cost after receiving")
    
    # Procurement specific fields
    delivery_instructions = models.TextField(blank=True, help_text="Delivery instructions")
    
    # Procurement specific dates
    expected_delivery = models.DateField(null=True, blank=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    ordered_at = models.DateTimeField(blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True)
    
    # User tracking
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_purchase_orders')
    
    # Approvals - updated to use centralized approvals
    approvals = models.ManyToManyField('approvals.Approval', related_name='purchase_orders', blank=True)

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        super().save(*args, **kwargs)

    def generate_order_number(self):
        """Generate unique purchase order number"""
        # Use a different approach since self.id might not be available during creation
        import uuid
        unique_id = str(uuid.uuid4().int)[:6]
        return f"PO-{timezone.now().year}-{unique_id}"

    def __str__(self):
        return f"{self.order_number} ({self.status})"
    
    def approve_order(self, approved_by_user):
        """Approve the purchase order"""
        self.status = 'approved'
        self.approved_by = approved_by_user
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at'])
    
    def mark_as_ordered(self):
        """Mark order as placed with supplier"""
        self.status = 'ordered'
        self.ordered_at = timezone.now()
        self.save(update_fields=['status', 'ordered_at'])
    
    def mark_as_received(self):
        """
        Mark order as received
        CRITICAL: Triggers inventory update via linked Purchase
        """
        self.status = 'received'
        self.received_at = timezone.now()
        self.save(update_fields=['status', 'received_at'])
        
        # Update linked Purchase status to trigger stock increase
        try:
            from procurement.purchases.models import Purchase
            purchase = Purchase.objects.filter(purchase_order=self).first()
            if purchase:
                purchase.purchase_status = 'received'
                purchase.save()  # This triggers inventory update in Purchase.save()
                logger.info(f"Updated Purchase {purchase.purchase_id} status to 'received' for PO {self.order_number}")
        except Exception as e:
            logger.error(f"Error updating Purchase for PO {self.order_number}: {str(e)}")
    
    def cancel_order(self, reason=None):
        """Cancel the purchase order"""
        self.status = 'cancelled'
        self.save(update_fields=['status'])
    
    def get_approval_status(self):
        """Get the current approval status"""
        return self.approvals.filter(status='approved').count()
    
    def is_fully_approved(self):
        """Check if order is fully approved"""
        return self.get_approval_status() >= 2  # Assuming 2 approvals needed
    
    def filter_orders(self, filters):
        """Filter purchase orders based on criteria."""
        queryset = self.objects.all()
        
        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])
        
        if filters.get('supplier'):
            queryset = queryset.filter(supplier=filters['supplier'])
        
        if filters.get('date_from'):
            queryset = queryset.filter(order_date__gte=filters['date_from'])
        
        if filters.get('date_to'):
            queryset = queryset.filter(order_date__lte=filters['date_to'])
        
        return queryset


def generate_order_number():
    """Generate a unique order number format for purchase orders"""
    from django.utils import timezone
    # Get the next ID by counting existing orders
    next_id = PurchaseOrder.objects.count() + 1
    return f"PO-{timezone.now().year}-{next_id:06d}"


# OrderApproval moved to centralized approvals app - import from there


class PurchaseOrderPayment(models.Model):
    """
    CRITICAL: Link Purchase Orders to Finance Payment Module
    Ensures ALL money-OUT for procurement is tracked in Finance
    """
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='po_payments')
    payment = models.ForeignKey('payment.Payment', on_delete=models.CASCADE, related_name='purchase_order_payments')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_account = models.ForeignKey('accounts.PaymentAccounts', on_delete=models.PROTECT)
    payment_date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Purchase Order Payment'
        verbose_name_plural = 'Purchase Order Payments'
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['purchase_order'], name='idx_po_payment_po'),
            models.Index(fields=['payment'], name='idx_po_payment_payment'),
            models.Index(fields=['payment_date'], name='idx_po_payment_date'),
        ]
    
    def __str__(self):
        return f"{self.purchase_order.order_number} - Payment {self.amount}"
    
    def save(self, *args, **kwargs):
        # Update purchase order's amount_paid
        super().save(*args, **kwargs)
        
        # Recalculate PO's total paid amount
        from django.db.models import Sum
        total_paid = PurchaseOrderPayment.objects.filter(
            purchase_order=self.purchase_order
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
        self.purchase_order.amount_paid = total_paid
        self.purchase_order.balance_due = self.purchase_order.total - total_paid
        
        # Update payment status
        if self.purchase_order.balance_due <= 0:
            self.purchase_order.payment_status = 'paid'
        elif self.purchase_order.amount_paid > 0:
            self.purchase_order.payment_status = 'partial'
        
        PurchaseOrder.objects.filter(pk=self.purchase_order.pk).update(
            amount_paid=total_paid,
            balance_due=self.purchase_order.balance_due,
            payment_status=self.purchase_order.payment_status
        )
