from .models import Expense
from django.utils import timezone

def generate_enxpense_ref(prefix):
    current_year = timezone.now().year
    # Assuming you have a Contact model with a field named 'contact_id'
    latest_expense = Expense.objects.order_by('-reference_no').first()
    if latest_expense:
        last_id = int(latest_expense.reference_no[5:])  # Extract the numeric part and convert to int
        new_id = last_id + 1
    else:
        new_id = 1
    # Format the new ID with current year and leading zeros
    formatted_id = f'{prefix}{current_year}{new_id:06d}'
    return formatted_id