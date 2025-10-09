"""
Signal handlers for the ecommerce order module.
These signals manage order lifecycle events including payment status changes,
inventory allocation, and integration with other systems.
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db.models import Sum
import logging
from .models import Order
from core_orders.models import OrderItem, OrderPayment

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Order)
def handle_order_status_change(sender, instance, created, **kwargs):
    """Track order lifecycle events and perform required actions"""
    if created:
        # New order created - this will be handled directly in the creation flow
        pass
    else:
        # Handle order status changes
        try:
            # We need to check the status changes that might require additional processing
            # These are handled here for background processing that doesn't fit directly
            # in the order orchestration service
            
            # Log order status change for record keeping
            logger.info(f"Order {instance.order_id} status changed to {instance.status}")
        except Exception as e:
            logger.error(f"Error handling order status change: {str(e)}")

@receiver(post_save, sender=OrderPayment)
def update_order_payment_status(sender, instance, created, **kwargs):
    """Update order payment status after a payment is recorded"""
    if not created and not kwargs.get('raw', False):
        return  # Only process new payments
        
    try:
        order = instance.order
        
        # Calculate total paid amount using centralized Payment status
        total_paid = (
            OrderPayment.objects
            .filter(order=order, payment__status__in=['completed'])
            .aggregate(total=Sum('payment__amount'))
            .get('total', 0)
            or 0
        )
        
        # Update order payment fields
        order.amount_paid = total_paid
        order.balance_due = max(0, order.order_amount - total_paid)
        
        # Update payment status
        if order.balance_due <= 0:
            order.payment_status = 'paid'
        elif order.amount_paid > 0:
            order.payment_status = 'partial'
        else:
            order.payment_status = 'pending'
            
        # If payment is complete and order is pending, move to processing
        if order.payment_status == 'paid' and order.status == 'pending':
            order.status = 'processing'
            
        order.save(update_fields=['amount_paid', 'balance_due', 'payment_status', 'status'])
        
    except Exception as e:
        logger.error(f"Error updating order payment status: {str(e)}")

@receiver(post_save, sender=OrderItem)
def handle_order_item_changes(sender, instance, created, **kwargs):
    """Track changes to order items and update inventory as needed"""
    if not created and not kwargs.get('raw', False):
        # If an existing order item is being modified, we may need to update inventory
        try:
            # Check if quantity has changed
            if hasattr(instance, '_original_quantity') and instance._original_quantity != instance.quantity:
                # Handle quantity change - this would update inventory
                pass
                
            # Update order amounts
            order = instance.order
            order.update_order_amount()
            order.save()
        except Exception as e:
            logger.error(f"Error handling order item change: {str(e)}")

# Add a pre_save handler to capture original values before saving
@receiver(pre_save, sender=OrderItem)
def store_original_values(sender, instance, **kwargs):
    """Store original values before saving to compare in post_save"""
    if instance.pk:
        try:
            original = OrderItem.objects.get(pk=instance.pk)
            instance._original_quantity = original.quantity
        except OrderItem.DoesNotExist:
            pass



@receiver(post_save, sender=Order)
def create_order_history(sender, instance, created, **kwargs):
    """Create order history entry when order status changes"""
    if created:
        pass
    

@receiver(pre_save, sender=Order)
def track_order_status_change(sender, instance, **kwargs):
    """Track status changes in order"""
    if instance.pk:  # If this is an update, not a new instance
        try:
            old_instance = Order.objects.get(pk=instance.pk)
            if old_instance.status != instance.status:
                pass
        except Order.DoesNotExist:
            pass


@receiver(post_save, sender=OrderPayment)
def update_order_after_payment(sender, instance, created, **kwargs):
    """Update order payment status after payment is created or updated"""
    # When a related Payment is updated to completed, update aggregate amounts
    if instance.payment and instance.payment.status == 'completed':
        order = instance.order
        total_paid = (
            OrderPayment.objects
            .filter(order=order, payment__status='completed')
            .aggregate(total=Sum('payment__amount'))
            .get('total', 0)
            or 0
        )
        order.amount_paid = total_paid
        order.balance_due = max(0, (order.order_amount or 0) - total_paid)
        # Set payment status
        if order.balance_due <= 0:
            order.payment_status = 'paid'
        elif order.amount_paid > 0:
            order.payment_status = 'partial'
        else:
            order.payment_status = 'pending'
        order.save(update_fields=['amount_paid', 'balance_due', 'payment_status'])
        
