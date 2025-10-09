# tasks.py
from celery import shared_task
from django.db import transaction

from ecommerce.pos.models import *
from ecommerce.stockinventory.models import *
from procurement.purchases.models import *

@shared_task
def create_initial_stock_transaction_task(stock_inventory_id):
    """
    Celery task to create an initial stock transaction.
    """
    try:
        stock_inventory = StockInventory.objects.get(id=stock_inventory_id)
        with transaction.atomic():
            StockTransaction.objects.update_or_create(
                transaction_type='INITIAL',
                stock_item=stock_inventory,
                location=stock_inventory.location,
                quantity=stock_inventory.stock_level
            )
        print(f"Initial stock transaction created for StockInventory {stock_inventory_id}.")
    except Exception as e:
        print(f"Error creating initial stock transaction: {e}")

@shared_task
def update_stock_transactions_task(stock_adjustment_id):
    """
    Celery task to update stock transactions for a stock adjustment.
    """
    try:
        stock_adjustment = StockAdjustment.objects.get(id=stock_adjustment_id)
        with transaction.atomic():
            transaction_type = 'ADJUSTMENT'
            quantity = stock_adjustment.quantity_adjusted if stock_adjustment.adjustment_type == 'increase' else -stock_adjustment.quantity_adjusted
            StockTransaction.objects.update_or_create(
                transaction_type=transaction_type,
                transaction_date=stock_adjustment.adjusted_at,
                stock_item=stock_adjustment.stock_item,
                location=stock_adjustment.location,
                quantity=quantity
            )
        print(f"Stock transaction updated for StockAdjustment {stock_adjustment_id}.")
    except Exception as e:
        print(f"Error updating stock transaction: {e}")

@shared_task
def create_stock_transaction_task(instance_id, instance_type):
    """
    Celery task to create stock transactions for Purchase, Sales, PurchaseReturn, or SalesReturn.
    """
    try:
        with transaction.atomic():
            if instance_type == 'Purchase':
                instance = Purchase.objects.get(id=instance_id)
                transaction_type = 'PURCHASE'
                items = instance.purchaseitems.all()
            elif instance_type == 'Sales':
                instance = Sales.objects.get(id=instance_id)
                transaction_type = 'SALE'
                items = instance.salesitems.all()
            elif instance_type == 'PurchaseReturn':
                instance = PurchaseReturn.objects.get(id=instance_id)
                transaction_type = 'PURCHASE_RETURN'
                items = instance.purchase_return_items.all()
            elif instance_type == 'SalesReturn':
                instance = SalesReturn.objects.get(id=instance_id)
                transaction_type = 'SALE_RETURN'
                items = instance.return_items.all()
            else:
                raise ValueError(f"Invalid instance type: {instance_type}")

            for item in items:
                StockTransaction.objects.update_or_create(
                    transaction_type=transaction_type,
                    location=instance.location if hasattr(instance, 'location') else item.stock_item.location,
                    stock_item=item.stock_item,
                    quantity=item.qty
                )
            print(f"Stock transactions created for {instance_type} {instance_id}.")
    except Exception as e:
        print(f"Error creating stock transaction: {e}")