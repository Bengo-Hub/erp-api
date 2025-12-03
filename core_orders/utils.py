"""
Utility functions for order processing and item management
"""
from django.db import transaction
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


def auto_create_product_from_item(item_data, branch, category_name=None):
    """
    Auto-create product and stock inventory from custom line item
    
    Args:
        item_data: Dict containing item details (name, description, unit_price, etc.)
        branch: Branch object where product should be created
        category_name: Optional category for the product
    
    Returns:
        StockInventory object or None
    """
    try:
        from ecommerce.product.models import Product, ProductCategory
        from ecommerce.stockinventory.models import StockInventory
        
        # Check if product already exists by name
        product_name = item_data.get('name')
        if not product_name:
            logger.warning('Cannot create product without name')
            return None
        
        # Try to find existing product by name
        existing_stock = StockInventory.objects.filter(
            product__title__iexact=product_name,
            branch=branch
        ).first()
        
        if existing_stock:
            logger.info(f'Using existing product: {product_name}')
            return existing_stock
        
        with transaction.atomic():
            # Get or create category
            category = None
            if category_name:
                category, _ = ProductCategory.objects.get_or_create(
                    name=category_name,
                    defaults={'status': 'active'}
                )
            
            # Create product
            product = Product.objects.create(
                title=product_name,
                description=item_data.get('description', ''),
                sku=f"AUTO-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                serial=f"SER-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                category=category,
                status='active',
                is_featured=False
            )
            
            # Create stock inventory
            stock = StockInventory.objects.create(
                product=product,
                branch=branch,
                buying_price=item_data.get('unit_price', 0),
                selling_price=item_data.get('unit_price', 0),
                stock_level=item_data.get('quantity', 0),
                reorder_level=10,
                usage='New',
                availability='In Stock',
                product_type='single'
            )
            
            logger.info(f'✅ Auto-created product: {product_name} (ID: {product.id})')
            return stock
    
    except Exception as e:
        logger.error(f'❌ Error auto-creating product: {str(e)}', exc_info=True)
        return None


def should_create_as_asset(item_data, category_name=None):
    """
    Determine if an item should be created as an asset
    
    Criteria:
    - Unit price >= KES 50,000 (capital asset threshold)
    - Category contains keywords: equipment, furniture, vehicle, computer, machinery
    - Quantity is 1 (assets are typically singular)
    
    Args:
        item_data: Dict containing item details
        category_name: Category name for classification
    
    Returns:
        bool: True if should be created as asset
    """
    # Check price threshold
    unit_price = float(item_data.get('unit_price', 0))
    if unit_price >= 50000:
        return True
    
    # Check category keywords
    if category_name:
        asset_keywords = ['equipment', 'furniture', 'vehicle', 'computer', 'machinery', 
                         'tools', 'appliance', 'fixture', 'hardware']
        category_lower = category_name.lower()
        if any(keyword in category_lower for keyword in asset_keywords):
            return True
    
    # Check item name for asset indicators
    item_name = item_data.get('name', '').lower()
    asset_indicators = ['laptop', 'desktop', 'server', 'printer', 'scanner', 'desk', 
                       'chair', 'table', 'vehicle', 'car', 'truck', 'generator']
    if any(indicator in item_name for indicator in asset_indicators):
        return True
    
    return False


def auto_create_asset_from_item(item_data, branch, created_by=None):
    """
    Auto-create asset from custom line item
    
    Args:
        item_data: Dict containing item details
        branch: Branch object
        created_by: User who created the item
    
    Returns:
        Asset object or None
    """
    try:
        from assets.models import Asset, AssetCategory
        
        item_name = item_data.get('name')
        if not item_name:
            return None
        
        with transaction.atomic():
            # Get or create asset category
            category_name = item_data.get('category', 'General Equipment')
            asset_category, _ = AssetCategory.objects.get_or_create(
                name=category_name,
                defaults={
                    'description': f'Auto-created category for {category_name}'
                }
            )
            
            # Create asset
            asset = Asset.objects.create(
                name=item_name,
                description=item_data.get('description', ''),
                category=asset_category,
                purchase_date=timezone.now().date(),
                purchase_cost=item_data.get('unit_price', 0) * item_data.get('quantity', 1),
                current_value=item_data.get('unit_price', 0) * item_data.get('quantity', 1),
                branch=branch,
                status='active',
                depreciation_method='straight_line',
                useful_life_years=5,  # Default 5 years
                residual_value=0,
                created_by=created_by
            )
            
            logger.info(f'✅ Auto-created asset: {item_name} (ID: {asset.id})')
            return asset
    
    except Exception as e:
        logger.error(f'❌ Error auto-creating asset: {str(e)}', exc_info=True)
        return None


def process_custom_items(items, branch, order_type='invoice', category_name=None, created_by=None):
    """
    Process custom line items and auto-create products/assets as needed
    
    Args:
        items: List of item dicts
        branch: Branch object
        order_type: Type of order (invoice, quotation, expense, etc.)
        category_name: Optional category for products
        created_by: User creating the items
    
    Returns:
        List of processed items with product_id and asset_id where applicable
    """
    processed_items = []
    
    for item in items:
        processed_item = item.copy()
        
        # Skip if item already has a product_id
        if item.get('product_id'):
            processed_items.append(processed_item)
            continue
        
        # Check if this should be an asset
        if should_create_as_asset(item, category_name):
            asset = auto_create_asset_from_item(item, branch, created_by)
            if asset:
                processed_item['asset_id'] = asset.id
                processed_item['is_asset'] = True
                logger.info(f'✅ Item "{item.get("name")}" created as Asset')
        
        # Create as product/inventory (even if it's an asset, for inventory tracking)
        stock = auto_create_product_from_item(item, branch, category_name)
        if stock:
            processed_item['product_id'] = stock.product.id
            processed_item['stock_id'] = stock.id
            logger.info(f'✅ Item "{item.get("name")}" created as Product')
        
        processed_items.append(processed_item)
    
    return processed_items

