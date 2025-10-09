from datetime import datetime
from django.db import models
from core.models import Departments
from approvals.models import Approval
from crm.contacts.models import Contact
from ecommerce.stockinventory.models import StockInventory
from django.contrib.auth import get_user_model

User = get_user_model()

class ProcurementRequest(models.Model):
    """Base model for all procurement requests"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('procurement_review', 'Procurement Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('ordered', 'Ordered'),
        ('completed', 'Completed'),
    ]
    
    REQUEST_TYPES = [
        ('inventory', 'Existing Inventory Item'),
        ('external_item', 'External Item Purchase'),
        ('service', 'External Service/Consultancy')
    ]

    PRIORITIES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical')
    ]
    reference_number = models.CharField(max_length=20, unique=True, blank=True)
    requester = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='procurement_requests')
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPES)
    purpose = models.TextField()
    priority = models.CharField(max_length=20, choices=PRIORITIES, default='medium')
    required_by_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approvals = models.ManyToManyField(Approval, related_name='procurement_requests', blank=True)

    def __str__(self):
        return f"PR-{self.id:06d} ({self.get_request_type_display()})"
    
    def generate_request_reference(self):
        # Use a temporary reference if ID is not available yet
        if self.id:
            return f"PRF-{datetime.now().year}-{self.id:06d}"
        else:
            # Generate a temporary reference that will be updated after save
            return f"PRF-{datetime.now().year}-TEMP"
    
    def save(self, *args, **kwargs):
        # First save to get the ID
        super().save(*args, **kwargs)
        
        # Now generate the proper reference number if it's still temporary
        if self.reference_number is None or self.reference_number == '' or 'TEMP' in self.reference_number:
            self.reference_number = self.generate_request_reference()
            # Update without triggering save again
            ProcurementRequest.objects.filter(id=self.id).update(reference_number=self.reference_number)
        
        return self

    class Meta:
        indexes = [
            models.Index(fields=['reference_number'], name='idx_procurement_request_ref'),
            models.Index(fields=['requester'], name='idx_proc_request_user'),
            models.Index(fields=['request_type'], name='idx_proc_request_type'),
            models.Index(fields=['priority'], name='idx_proc_request_priority'),
            models.Index(fields=['required_by_date'], name='idx_proc_request_required'),
            models.Index(fields=['status'], name='idx_procurement_request_status'),
            models.Index(fields=['created_at'], name='idx_proc_request_created'),
            models.Index(fields=['updated_at'], name='idx_proc_request_updated'),
        ]

    

class RequestItem(models.Model):
    """Unified model to handle all request item types"""
    ITEM_TYPES = [
        ('inventory', 'Inventory Item'),
        ('external', 'External Item'),
        ('service', 'Service')
    ]
    
    request = models.ForeignKey(ProcurementRequest, on_delete=models.CASCADE, related_name='items')
    item_type = models.CharField(max_length=20, choices=ITEM_TYPES)
    
    # Fields for inventory items
    stock_item = models.ForeignKey(StockInventory, on_delete=models.CASCADE, null=True, blank=True, related_name='request_items')
    quantity = models.PositiveIntegerField(default=1)
    approved_quantity = models.PositiveIntegerField(null=True, blank=True)
    urgent = models.BooleanField(default=False)
    
    # Fields for external items
    description = models.TextField(blank=True)
    specifications = models.TextField(blank=True)
    estimated_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    supplier = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Fields for services
    service_description = models.TextField(blank=True)
    expected_deliverables = models.TextField(blank=True)
    duration = models.CharField(max_length=100, blank=True)
    provider = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name='service_items')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    
    def __str__(self):
        if self.item_type == 'inventory' and self.stock_item:
            return f"Inventory: {self.stock_item} x{self.quantity}"
        elif self.item_type == 'external':
            return f"External: {self.description} x{self.quantity}"
        elif self.item_type == 'service':
            return f"Service: {self.service_description}"
        return f"Request Item #{self.id}"

    class Meta:
        indexes = [
            models.Index(fields=['request'], name='idx_request_item_request'),
            models.Index(fields=['item_type'], name='idx_request_item_item_type'),
            models.Index(fields=['stock_item'], name='idx_request_item_stock_item'),
            models.Index(fields=['supplier'], name='idx_request_item_supplier'),
            models.Index(fields=['provider'], name='idx_request_item_provider'),
            models.Index(fields=['urgent'], name='idx_request_item_urgent'),
        ]

    def clean(self):
        """Validate that the correct fields are filled based on item_type"""
        from django.core.exceptions import ValidationError
        
        if self.item_type == 'inventory':
            if not self.stock_item:
                raise ValidationError("Stock item is required for inventory items")
        elif self.item_type == 'external':
            if not self.description:
                raise ValidationError("Description is required for external items")
        elif self.item_type == 'service':
            if not self.service_description:
                raise ValidationError("Service description is required for services")

    def get_total_cost(self):
        """Calculate total cost based on item type"""
        if self.item_type == 'inventory' and self.stock_item:
            return self.stock_item.unit_price * self.quantity
        elif self.item_type == 'external' and self.estimated_price:
            return self.estimated_price * self.quantity
        elif self.item_type == 'service' and self.estimated_price:
            return self.estimated_price
        return 0

    

class ServiceDelivery(models.Model):
    request = models.OneToOneField(RequestItem, on_delete=models.CASCADE)
    provider = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True)
    start_date = models.DateField()
    end_date = models.DateField()
    deliverables = models.TextField()
    status = models.CharField(max_length=20, choices=[
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('delayed', 'Delayed')
    ])

    
    def __str__(self):
        return f"Service delivery for {self.request}"
    
    class Meta:
        indexes = [
            models.Index(fields=['request'], name='idx_service_delivery_request'),
            models.Index(fields=['provider'], name='idx_service_delivery_provider'),
            models.Index(fields=['start_date'], name='idx_service_delivery_start'),
            models.Index(fields=['end_date'], name='idx_service_delivery_end_date'),
            models.Index(fields=['status'], name='idx_service_delivery_status'),
        ]
    


# RequestApproval moved to centralized approvals app - import from there
