import random
import django.utils.timezone as django_timezone

def generate_ref_no(prefix='STR'):
    current_year = django_timezone.now().year
    # Assuming you have a Contact model with a field named 'contact_id'
    last_id = random.randint(1,10) 
    new_id = last_id + 1
    # Format the new ID with current year and leading zeros
    formatted_id = f'{prefix}{current_year}{new_id:06d}'
    return formatted_id