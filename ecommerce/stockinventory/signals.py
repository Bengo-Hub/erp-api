from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import *
from ecommerce.pos.models import *
from procurement.purchases.models import *
from django.db import transaction

@receiver(post_save, sender=StockInventory)
def create_initial_stock_transaction(sender, instance, created, **kwargs):
    print('StockInventory:post save signal...',created)
    if created:
        with transaction.atomic():
            _,created=StockTransaction.objects.update_or_create(
                transaction_type='INITIAL',
                stock_item=instance,
                branch=instance.branch,
                quantity=instance.stock_level,
            )

@receiver(post_save, sender=StockAdjustment)
def update_stock_transactions(sender, instance, created, **kwargs):
    print('StockAdjustment:post save signal...',created)
    if created:
        with transaction.atomic():
            transaction_type = 'ADJUSTMENT'
            if instance.adjustment_type == 'increase':
                quantity = instance.quantity_adjusted
            else:
                quantity = -instance.quantity_adjusted
            _,created=StockTransaction.objects.update_or_create(
                transaction_type=transaction_type,
                transaction_date=instance.adjusted_at,
                stock_item=instance.stock_item,
                branch=instance.stock_item.branch,
                quantity=quantity
            )

@receiver(post_save, sender=Purchase)
@receiver(post_save, sender=Sales)
@receiver(post_save, sender=PurchaseReturn)
@receiver(post_save, sender=SalesReturn)
@receiver(post_save, sender=StockTransfer)
def create_stock_transaction(sender, instance, created, **kwargs):
    print('All:post save signal...',created)
    #if created:
    try:
        items=[]
        with transaction.atomic():
            # For purchases, only create stock transactions when a purchase is received
            if isinstance(instance, Purchase):
                if instance.purchase_status != 'received':
                    # Do not create purchase stock transactions until the purchase is marked as received
                    return
                transaction_type = 'PURCHASE'
                items = instance.purchaseitems.all()
            elif isinstance(instance, Sales):
                transaction_type = 'SALE'
                items = instance.salesitems.all()
            elif isinstance(instance, PurchaseReturn):
                transaction_type = 'PURCHASE_RETURN'
                items = instance.purchase_return_items.all()
            elif isinstance(instance, SalesReturn):
                transaction_type = 'SALE_RETURN'
                items = instance.return_items.all()
            elif isinstance(instance, StockTransfer) and instance.status == 'Completed':
                transaction_type = 'TRANSFER_IN'
                items = instance.transfer_items.all()
            for item in items:
                # Default branch from stock item
                current_branch = item.stock_item.branch
                if 'TRANSFER' in transaction_type and hasattr(instance, 'branch_from'):
                    if current_branch == instance.branch_from:
                        t_type = 'TRANSFER_OUT'
                    else:
                        t_type = 'TRANSFER_IN'
                else:
                    t_type = transaction_type

                # If this is a Purchase, attach a reference to the purchase so we can be idempotent
                if isinstance(instance, Purchase):
                    lookup = {
                        'transaction_type': t_type,
                        'stock_item': item.stock_item,
                        'purchase': instance
                    }
                    defaults = {
                        'branch': instance.branch if hasattr(instance, 'branch') else item.stock_item.branch,
                        'quantity': item.qty if hasattr(item, 'qty') else item.quantity
                    }
                    _, created = StockTransaction.objects.update_or_create(**lookup, defaults=defaults)
                else:
                    # Other transaction types (sales, returns, transfers) remain unchanged
                    _, created = StockTransaction.objects.update_or_create(
                        transaction_type=t_type,
                        branch=instance.branch if hasattr(instance, 'branch') else item.stock_item.branch,
                        stock_item=item.stock_item,
                        quantity=item.qty if hasattr(item, 'qty') else item.quantity
                    )
                
    except Exception as e:
        # Handle the exception here (e.g., log the error)
        print(f"Error occurred while creating stock transaction: {e}")