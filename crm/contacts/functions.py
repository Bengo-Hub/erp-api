from .models import Contact
from django.utils import timezone
import re

def generate_contact_id(prefix):
    current_year = timezone.now().year
    # Get contacts with IDs matching the expected format (CYYYYNNNNN)
    # to avoid parsing non-standard IDs like "FAULT-1"
    expected_format = f'{prefix}{current_year}'
    
    # Get the latest contact with the current year prefix
    latest_contact = Contact.objects.filter(
        contact_id__startswith=expected_format
    ).order_by('-contact_id').first()
    
    if latest_contact:
        try:
            # Extract only the numeric part after the prefix and year
            numeric_part = latest_contact.contact_id[len(expected_format):]
            # Extract digits from the numeric part (in case there's other characters)
            numbers = re.findall(r'\d+', numeric_part)
            if numbers:
                last_id = int(numbers[0])
                new_id = last_id + 1
            else:
                new_id = 1
        except (ValueError, IndexError):
            # If we can't parse, start fresh
            new_id = 1
    else:
        new_id = 1
    
    # Format the new ID with current year and leading zeros
    formatted_id = f'{prefix}{current_year}{new_id:06d}'
    return formatted_id
