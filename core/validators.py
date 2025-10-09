from datetime import date
from decimal import Decimal, InvalidOperation
from rest_framework import serializers
import re


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

_PHONE_RE = re.compile(r"^(?:\+?254|0)\d{9}$")

def validate_kenyan_phone(value: str) -> None:
    if value and not _PHONE_RE.match(str(value)):
        raise serializers.ValidationError({"phone_number": "Invalid Kenyan phone number"})
    return None

