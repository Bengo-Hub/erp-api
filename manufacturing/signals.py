from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.db import transaction

from .models import ProductionBatch, ManufacturingAnalytics, QualityCheck, RawMaterialUsage
from ecommerce.stockinventory.models import StockInventory


@receiver(post_save, sender=ProductionBatch)
def update_analytics_on_batch_change(sender, instance, created, **kwargs):
    """
    Update manufacturing analytics when a production batch is created or updated
    """
    if created or instance.status in ['completed', 'failed']:
        # Get or create analytics for today
        date = timezone.now().date()
        ManufacturingAnalytics.update_for_date(date)


@receiver(post_save, sender=QualityCheck)
def handle_quality_check_result(sender, instance, created, **kwargs):
    """
    Handle actions when a quality check is performed
    """
    if created and instance.result == 'fail':
        batch = instance.batch
        # If quality check fails, update the batch status
        if batch.status == 'completed':
            batch.status = 'failed'
            batch.notes = (batch.notes or '') + f"\nFailed quality check on {timezone.now()}: {instance.notes}"
            batch.save(update_fields=['status', 'notes'])


@receiver(pre_save, sender=ProductionBatch)
def update_stock_on_batch_complete(sender, instance, **kwargs):
    """
    Update stock levels when a batch is completed
    """
    # Check if this is an existing batch being updated to 'completed'
    if instance.pk:
        try:
            old_instance = ProductionBatch.objects.get(pk=instance.pk)
            # Only proceed if status is changing from something else to 'completed'
            if old_instance.status != 'completed' and instance.status == 'completed' and instance.actual_quantity:
                with transaction.atomic():
                    # Add produced product to inventory
                    final_product = instance.formula.final_product
                    #create a new stock inventory record if not already present else update the existing one
                    try:
                        stock_inventory = StockInventory.objects.get(product=final_product)
                    except StockInventory.DoesNotExist:
                        stock_inventory = None
                    if stock_inventory:
                        stock_inventory.stock_level += instance.actual_quantity
                        stock_inventory.save(update_fields=['stock_level'])
                        # create stock transaction
                        stock_inventory.create_stock_transaction(
                            transaction_type='PRODUCTION',
                            quantity=instance.actual_quantity,
                            notes=f"Produced in Batch #{instance.batch_number}"
                        )
                    else:
                        stock_inventory = StockInventory.objects.create(
                            product=final_product,
                            stock_level=instance.actual_quantity,
                            location=instance.location,
                            is_new_arrival=True,
                            buying_price=instance.get_unit_cost(),
                            selling_price=instance.suggested_selling_price(),
                        )
                    stock_inventory.stock_level += instance.actual_quantity
                    stock_inventory.manufacturing_cost = instance.get_unit_cost()
                    stock_inventory.save(update_fields=['stock_level', 'manufacturing_cost'])

                    # Record raw material usage
                    for material_usage in instance.raw_materials.all():
                        if material_usage.actual_quantity is None:
                            material_usage.actual_quantity = material_usage.planned_quantity
                            material_usage.save(update_fields=['actual_quantity'])
                            
                        RawMaterialUsage.objects.create(
                            finished_product=final_product,
                            raw_material=material_usage.raw_material,
                            quantity_used=material_usage.actual_quantity,
                            transaction_type='production',
                            notes=f"Used in Batch #{instance.batch_number}"
                        )
                        
        except ProductionBatch.DoesNotExist:
            pass  # This is a new instance
