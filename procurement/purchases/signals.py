from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Purchase

@receiver(post_save, sender=Purchase)
def update_purchase_order_status(sender, instance, **kwargs):
    """
    Update linked purchase order status when purchase status changes
    """
    if instance.purchase_order:
        if instance.purchase_status == 'received':
            instance.purchase_order.status = 'fulfilled'
            instance.purchase_order.actual_cost = instance.grand_total
            instance.purchase_order.save()
            
