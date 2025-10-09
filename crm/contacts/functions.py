from .models import Contact
from django.utils import timezone

def generate_contact_id(prefix):
    current_year = timezone.now().year
    # Assuming you have a Contact model with a field named 'contact_id'
    latest_contact = Contact.objects.order_by('-contact_id').first()
    if latest_contact:
        last_id = int(latest_contact.contact_id[6:])  # Extract the numeric part and convert to int
        new_id = last_id + 1
    else:
        new_id = 1
    # Format the new ID with current year and leading zeros
    formatted_id = f'{prefix}{current_year}{new_id:06d}'
    return formatted_id
