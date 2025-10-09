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


from django.contrib.auth import get_user_model
User = get_user_model()

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
        """Mark order as received"""
        self.status = 'received'
        self.received_at = timezone.now()
        self.save(update_fields=['status', 'received_at'])
    
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
