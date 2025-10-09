#signal to create purchase when order is approved
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from .models import PurchaseOrder
from procurement.purchases.models import Purchase,PurchaseItems
from .functions import generate_purchase_order


@receiver(post_save, sender=PurchaseOrder)
def create_purchase(sender, instance, **kwargs):
    if instance.status == 'approved':
        with transaction.atomic():
            purchase=Purchase.objects.create(
            purchase_order=instance,
            supplier=instance.supplier,
            purchase_id=generate_purchase_order(instance.id),
            grand_total=instance.approved_budget,
            sub_total=instance.approved_budget,
            purchase_status='ordered'
            )
            #add purchase items
            for item in instance.requisition.items.all():
                PurchaseItems.objects.create(
                    purchase=purchase,
                    stock_item=item.stock_item,
                    qty=item.quantity,
                    unit_price=item.stock_item.buying_price
                )
