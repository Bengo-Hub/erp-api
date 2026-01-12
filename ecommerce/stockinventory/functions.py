import django.utils.timezone as django_timezone
import re


def generate_ref_no(prefix='STR'):
    """
    Generate a unique reference number with format: PREFIX-YYYY-NNNNNN

    Args:
        prefix: The document type prefix (e.g., 'STR' for stock transfer, 'PO' for purchase order)

    Returns:
        str: A unique reference number like 'STR-2026-000001'
    """
    current_year = django_timezone.now().year

    # Determine which model to query based on prefix
    if prefix == 'STR':
        from ecommerce.stockinventory.models import StockTransfer
        model = StockTransfer
        ref_field = 'ref_no'
    elif prefix == 'PO':
        from procurement.purchases.models import Purchases
        model = Purchases
        ref_field = 'purchase_id'
    elif prefix == 'ADJ':
        from ecommerce.stockinventory.models import StockAdjustment
        model = StockAdjustment
        ref_field = 'ref_no'
    else:
        # Default fallback - use timestamp for uniqueness
        import uuid
        unique_id = str(uuid.uuid4().int)[:6]
        return f'{prefix}-{current_year}-{unique_id}'

    # Get the latest reference number for this prefix and year
    year_pattern = f'{prefix}-{current_year}-'
    try:
        # Query for the latest record with this year's prefix
        latest = model.objects.filter(
            **{f'{ref_field}__startswith': year_pattern}
        ).order_by(f'-{ref_field}').first()

        if latest:
            ref_value = getattr(latest, ref_field, None)
            if ref_value:
                # Extract the sequence number from the reference
                match = re.search(r'-(\d{6})$', ref_value)
                if match:
                    last_seq = int(match.group(1))
                    new_seq = last_seq + 1
                else:
                    new_seq = 1
            else:
                new_seq = 1
        else:
            new_seq = 1
    except Exception:
        # If model doesn't exist or query fails, start from 1
        new_seq = 1

    return f'{prefix}-{current_year}-{new_seq:06d}'