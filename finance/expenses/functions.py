from .models import Expense
from django.utils import timezone
import re


def generate_expense_ref(prefix='EP'):
    """
    Generate a unique expense reference number.

    Format: PREFIX-YYYY-NNNNNN (e.g., EP-2026-000001)

    Args:
        prefix: The expense prefix (default 'EP')

    Returns:
        str: A unique reference number
    """
    current_year = timezone.now().year
    year_pattern = f'{prefix}-{current_year}-'

    # Find the latest expense with this year's prefix
    latest_expense = Expense.objects.filter(
        reference_no__startswith=year_pattern
    ).order_by('-reference_no').first()

    if latest_expense and latest_expense.reference_no:
        # Extract the sequence number
        match = re.search(r'-(\d{6})$', latest_expense.reference_no)
        if match:
            last_seq = int(match.group(1))
            new_seq = last_seq + 1
        else:
            new_seq = 1
    else:
        new_seq = 1

    return f'{prefix}-{current_year}-{new_seq:06d}'


# Backward compatibility alias (typo fix)
generate_enxpense_ref = generate_expense_ref