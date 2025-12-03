"""
Asset Signals - Auto-creation from Capital Purchases
Automatically creates asset records when purchasing capital items
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from decimal import Decimal
import logging
import uuid

from procurement.purchases.models import Purchase, PurchaseItems
from .models import Asset, AssetCategory

logger = logging.getLogger(__name__)

# Capital asset threshold - purchases above this create assets
CAPITAL_ASSET_THRESHOLD = Decimal('50000.00')  # KES 50,000

# Category keywords that indicate capital assets
CAPITAL_KEYWORDS = [
    'computer', 'laptop', 'server', 'furniture', 'vehicle', 'equipment',
    'machinery', 'building', 'land', 'property', 'fixture', 'tool',
    'printer', 'scanner', 'projector', 'camera', 'generator'
]


@receiver(post_save, sender=Purchase)
def auto_create_assets_from_purchase(sender, instance, created, **kwargs):
    """
    CRITICAL: Auto-create assets for capital item purchases
    Triggered when Purchase status = 'received'
    """
    # Only process when purchase is received and not in raw mode
    if kwargs.get('raw', False):
        return
    
    if instance.purchase_status == 'received':
        try:
            with transaction.atomic():
                for item in instance.purchaseitems.all():
                    # Check if item qualifies as capital asset
                    if should_create_asset(item):
                        create_asset_from_purchase_item(item, instance)
        
        except Exception as e:
            logger.error(f"Error auto-creating assets for purchase {instance.purchase_id}: {str(e)}")


def should_create_asset(purchase_item: PurchaseItems) -> bool:
    """
    Determine if a purchase item should create an asset
    
    Criteria:
    1. Item value exceeds capital asset threshold
    2. Product category contains capital asset keywords
    3. Product is marked as capital asset
    """
    try:
        stock_item = purchase_item.stock_item
        product = stock_item.product
        
        # Check value threshold
        item_value = purchase_item.qty * purchase_item.unit_price
        if item_value >= CAPITAL_ASSET_THRESHOLD:
            logger.info(f"Purchase item {product.title} qualifies as capital asset (value: {item_value})")
            return True
        
        # Check product category for capital keywords
        if product.category:
            category_name = product.category.name.lower()
            for keyword in CAPITAL_KEYWORDS:
                if keyword in category_name:
                    logger.info(f"Purchase item {product.title} qualifies as capital asset (category: {category_name})")
                    return True
        
        # Check product title for capital keywords
        product_title = product.title.lower()
        for keyword in CAPITAL_KEYWORDS:
            if keyword in product_title:
                logger.info(f"Purchase item {product.title} qualifies as capital asset (title match)")
                return True
        
        # Check if product has is_capital_asset flag
        if hasattr(product, 'is_capital_asset') and product.is_capital_asset:
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"Error checking if purchase item should create asset: {str(e)}")
        return False


def create_asset_from_purchase_item(purchase_item: PurchaseItems, purchase: Purchase):
    """
    Create an asset record from a purchase item
    """
    try:
        stock_item = purchase_item.stock_item
        product = stock_item.product
        
        # Get or create appropriate asset category
        asset_category = get_or_create_asset_category(product.category)
        
        # Generate unique asset tag
        asset_tag = generate_asset_tag(product)
        
        # Calculate asset details
        purchase_cost = purchase_item.qty * purchase_item.unit_price
        
        # Create asset
        asset = Asset.objects.create(
            asset_tag=asset_tag,
            name=product.title,
            description=product.description or '',
            category=asset_category,
            serial_number=product.serial if hasattr(product, 'serial') else None,
            model=product.model if hasattr(product, 'model') else None,
            purchase_date=purchase.date_added.date() if purchase.date_added else timezone.now().date(),
            purchase_cost=purchase_cost,
            current_value=purchase_cost,
            salvage_value=purchase_cost * Decimal('0.1'),  # 10% salvage value
            depreciation_rate=asset_category.depreciation_rate if asset_category else Decimal('20.0'),
            depreciation_method='straight_line',
            branch=purchase.branch,
            status='active',
            condition='excellent',
            # Link to source purchase
            notes=f"Auto-created from Purchase {purchase.purchase_id}, Item: {product.title}"
        )
        
        logger.info(f"✅ Created asset {asset.asset_tag} from purchase {purchase.purchase_id}")
        return asset
    
    except Exception as e:
        logger.error(f"Error creating asset from purchase item: {str(e)}")
        return None


def get_or_create_asset_category(product_category):
    """Get or create matching asset category for product category"""
    if not product_category:
        category, _ = AssetCategory.objects.get_or_create(
            name='General Equipment',
            defaults={
                'description': 'General equipment and tools',
                'depreciation_rate': Decimal('20.0'),
                'useful_life_years': 5
            }
        )
        return category
    
    # Try to find existing asset category with similar name
    asset_category = AssetCategory.objects.filter(
        name__icontains=product_category.name
    ).first()
    
    if not asset_category:
        # Create new asset category
        asset_category, _ = AssetCategory.objects.get_or_create(
            name=product_category.name,
            defaults={
                'description': f'Assets from {product_category.name} category',
                'depreciation_rate': Decimal('20.0'),
                'useful_life_years': 5
            }
        )
    
    return asset_category


def generate_asset_tag(product):
    """Generate unique asset tag"""
    # Try to use product SKU/serial
    if hasattr(product, 'sku') and product.sku:
        base = product.sku[:4].upper()
    elif hasattr(product, 'serial') and product.serial:
        base = product.serial[:4].upper()
    else:
        base = product.title[:4].upper().replace(' ', '')
    
    # Add unique suffix
    unique_suffix = uuid.uuid4().hex[:6].upper()
    return f"AST-{base}-{unique_suffix}"

