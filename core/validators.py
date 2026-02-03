from datetime import date
from decimal import Decimal, InvalidOperation
from rest_framework import serializers
import re
import phonenumbers
from phonenumbers import NumberParseException
from django.core.validators import RegexValidator


def validate_date_range(start_date: date, end_date: date, field_start='start_date', field_end='end_date'):
    if start_date and end_date and end_date < start_date:
        raise serializers.ValidationError({
            field_end: f"{field_end} cannot be earlier than {field_start}"
        })


def validate_non_negative_decimal(value, field_name: str):
    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, TypeError):
        raise serializers.ValidationError({field_name: "Invalid decimal value"})

    if decimal_value < 0:
        raise serializers.ValidationError({field_name: f"{field_name} cannot be negative"})

    return decimal_value


def validate_required_fields(data: dict, required: list[str]):
    missing = [f for f in required if data.get(f) in (None, "", [])]
    if missing:
        raise serializers.ValidationError({f: "This field is required." for f in missing})


KENYAN_COUNTIES = {
    "Mombasa", "Kwale", "Kilifi", "Tana River", "Lamu", "Taita Taveta",
    "Garissa", "Wajir", "Mandera", "Marsabit", "Isiolo", "Meru",
    "Tharaka-Nithi", "Embu", "Kitui", "Machakos", "Makueni", "Nyandarua",
    "Nyeri", "Kirinyaga", "Murang'a", "Kiambu", "Turkana", "West Pokot",
    "Samburu", "Trans Nzoia", "Uasin Gishu", "Elgeyo-Marakwet", "Nandi",
    "Baringo", "Laikipia", "Nakuru", "Narok", "Kajiado", "Kericho",
    "Bomet", "Kakamega", "Vihiga", "Bungoma", "Busia", "Siaya",
    "Kisumu", "Homa Bay", "Migori", "Kisii", "Nyamira", "Nairobi"
}

def validate_kenyan_county(value: str) -> None:
    if value and value not in KENYAN_COUNTIES:
        raise serializers.ValidationError({"county": "Invalid Kenyan county"})
    return None

_POSTAL_RE = re.compile(r"^\d{5}$")

def validate_kenyan_postal_code(value: str) -> None:
    if value and not _POSTAL_RE.match(str(value)):
        raise serializers.ValidationError({"postal_code": "Postal code must be 5 digits"})
    return None


def validate_phone_number(value: str, region: str = None) -> None:
    """
    Validate phone number using phonenumbers library for global support.
    
    Args:
        value: Phone number string to validate
        region: Optional region code (e.g., 'KE' for Kenya, 'US' for USA). If None, tries to parse international format.
    
    Raises:
        serializers.ValidationError: If phone number is invalid
    """
    if not value:
        return None
    
    try:
        # Parse the phone number
        phone_obj = phonenumbers.parse(value, region)
        
        # Check if the number is valid
        if not phonenumbers.is_valid_number(phone_obj):
            raise serializers.ValidationError({
                "phone_number": "Invalid phone number format. Please include country code (e.g., +254700000000)"
            })
            
        return None
    except NumberParseException as e:
        raise serializers.ValidationError({
            "phone_number": f"Invalid phone number: {str(e)}"
        })


def validate_kenyan_phone(value: str) -> None:
    """
    Validate Kenyan phone number specifically.
    Kept for backward compatibility but uses phonenumbers library.
    """
    return validate_phone_number(value, region='KE')


def get_global_phone_validator(region: str = None):
    """
    Returns a RegexValidator that accepts international phone numbers.
    For use in Django models.
    
    Args:
        region: Optional default region code (e.g., 'KE', 'US', 'GB')
    
    Returns:
        RegexValidator instance that validates phone numbers
    """
    # This regex allows international format with + and digits, or local formats
    # It's intentionally permissive; real validation happens via phonenumbers library
    return RegexValidator(
        regex=r'^\+?[1-9]\d{1,14}$',  # E.164 format (international standard)
        message='Enter a valid phone number (e.g., +254700000000 or +14155552671)'
    )

