"""
Invoice Signals - Inventory Integration
Automatically updates stock levels when invoices are finalized
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db import transaction
import logging

from .models import Invoice
from ecommerce.stockinventory.models import StockInventory, StockTransaction

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Invoice)
def update_inventory_on_invoice_finalize(sender, instance, created, **kwargs):
    """
    CRITICAL: Reduce inventory when invoice is sent or paid
    Ensures inventory tracking for all sales (not just POS)
    """
    # Only process if invoice is being finalized (sent or paid)
    if kwargs.get('raw', False):
        return
    
    # Check if this is a status change to finalized state
    if instance.status in ['sent', 'paid']:
        try:
            with transaction.atomic():
                for item in instance.items.all():
                    # Check if item is linked to a stock item
                    if hasattr(item, 'content_object'):
                        if isinstance(item.content_object, StockInventory):
                            stock_item = item.content_object
                            
                            # Check if we have enough stock
                            if stock_item.stock_level >= item.quantity:
                                # Reduce stock level
                                stock_item.stock_level -= item.quantity
                                stock_item.save(update_fields=['stock_level'])
                                
                                # Create stock transaction record
                                StockTransaction.objects.create(
                                    transaction_type='SALE',
                                    stock_item=stock_item,
                                    branch=instance.branch or stock_item.branch,
                                    quantity=-item.quantity,  # Negative for stock OUT
                                    notes=f"Invoice {instance.invoice_number} - {item.name}",
                                    created_by=instance.created_by
                                )
                                
                                logger.info(f"Reduced stock for {stock_item} by {item.quantity} units (Invoice: {instance.invoice_number})")
                            else:
                                logger.warning(f"Insufficient stock for {stock_item}. Required: {item.quantity}, Available: {stock_item.stock_level}")
                    
                    # Alternative: If item has product_id, try to find stock
                    elif hasattr(item, 'product_id') and item.product_id:
                        try:
                            # Find stock item for this product in the branch
                            stock_item = StockInventory.objects.filter(
                                product_id=item.product_id,
                                branch=instance.branch
                            ).first()
                            
                            if stock_item and stock_item.stock_level >= item.quantity:
                                stock_item.stock_level -= item.quantity
                                stock_item.save(update_fields=['stock_level'])
                                
                                StockTransaction.objects.create(
                                    transaction_type='SALE',
                                    stock_item=stock_item,
                                    branch=instance.branch or stock_item.branch,
                                    quantity=-item.quantity,
                                    notes=f"Invoice {instance.invoice_number} - {item.name}",
                                    created_by=instance.created_by
                                )
                                
                                logger.info(f"Reduced stock for {stock_item} by {item.quantity} units (Invoice: {instance.invoice_number})")
                        except Exception as e:
                            logger.error(f"Error finding/updating stock for product {item.product_id}: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error updating inventory for invoice {instance.invoice_number}: {str(e)}")


@receiver(pre_save, sender=Invoice)
def track_invoice_status_change(sender, instance, **kwargs):
    """Track invoice status changes for audit purposes"""
    if instance.pk:
        try:
            old_instance = Invoice.objects.get(pk=instance.pk)
            if old_instance.status != instance.status:
                logger.info(f"Invoice {instance.invoice_number} status changed: {old_instance.status} → {instance.status}")
                
                # Store old status for reference in post_save
                instance._old_status = old_instance.status
        except Invoice.DoesNotExist:
            pass

