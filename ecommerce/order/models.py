from django.db import models
from django.utils import timezone
from crm.contacts.models import Contact
from ecommerce.stockinventory.models import StockInventory
from business.models import Branch
from addresses.models import AddressBook
from core_orders.models import BaseOrder, OrderItem, OrderPayment
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
import uuid

from django.contrib.auth import get_user_model
User = get_user_model()


class Order(BaseOrder):
    """
    E-commerce Order Model - Extends BaseOrder for e-commerce specific functionality
    """
    # E-commerce specific fields only (remove duplicates from BaseOrder)
    order_id = models.CharField(max_length=50, unique=True)
    
    # E-commerce specific inventory management
    inventory_reserved = models.BooleanField(default=False, help_text="Whether inventory has been reserved for this order")
    inventory_allocated = models.BooleanField(default=False, help_text="Whether inventory has been allocated for this order")
    inventory_reservation_expires = models.DateTimeField(null=True, blank=True, help_text="When the inventory reservation expires")
    backorder_items = models.JSONField(null=True, blank=True, help_text="Items that are backordered")
    
    # Customer Communication
    customer_notes = models.TextField(blank=True, null=True)
    internal_notes = models.TextField(blank=True, null=True)
    cancellation_reason = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'ecommerce_orders'
        verbose_name = 'E-commerce Order'
        verbose_name_plural = 'E-commerce Orders'

    def save(self, *args, **kwargs):
        if not self.order_id:
            self.order_id = self.generate_order_id()
        if not self.order_type:
            self.order_type = 'ecommerce'
        super().save(*args, **kwargs)

    def generate_order_id(self):
        """Generate unique e-commerce order ID"""
        return f"ECO-{timezone.now().year}-{uuid.uuid4().hex[:8].upper()}"

    def __str__(self):
        return f"{self.order_id} - {self.order_number}"

    def reserve_inventory(self):
        """Reserve inventory for this order"""
        if not self.inventory_reserved:
            # Logic to reserve inventory
            self.inventory_reserved = True
            self.inventory_reservation_expires = timezone.now() + timezone.timedelta(hours=24)
            self.save()

    def allocate_inventory(self):
        """Allocate inventory for this order"""
        if self.inventory_reserved and not self.inventory_allocated:
            # Logic to allocate inventory
            self.inventory_allocated = True
            self.save()

    def release_inventory_reservation(self):
        """Release inventory reservation"""
        if self.inventory_reserved and not self.inventory_allocated:
            self.inventory_reserved = False
            self.inventory_reservation_expires = None
            self.save()

