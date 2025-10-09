from .models import Sales,SalesReturn
from django.utils import timezone


def generate_sale_id(prefix='S'):
    current_year = timezone.now().year
    # Assuming you have a Contact model with a field named 'contact_id'
    latest_sale = Sales.objects.order_by('-sale_id').first()
    if latest_sale:
        last_id = int(latest_sale.sale_id[5:])  # Extract the numeric part and convert to int
        new_id = last_id + 1
    else:
        new_id = 1
    # Format the new ID with current year and leading zeros
    formatted_id = f'{prefix}{current_year}{new_id:06d}'
    return formatted_id

def generate_return_id(prefix='SR'):
    current_year = timezone.now().year
    # Assuming you have a Contact model with a field named 'contact_id'
    latest_return = SalesReturn.objects.order_by('-return_id').first()
    if latest_return:
        last_id = int(latest_return.return_id[5:])  # Extract the numeric part and convert to int
        new_id = last_id + 1
    else:
        new_id = 1
    # Format the new ID with current year and leading zeros
    formatted_id = f'{prefix}{current_year}{new_id:06d}'
    return formatted_id