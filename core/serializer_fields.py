"""
Custom Serializer Fields for BengoERP

Provides reusable serializer fields that add enhanced functionality
to standard Django REST Framework fields.
"""

from rest_framework import serializers
from decimal import Decimal


class MoneyField(serializers.DecimalField):
    """
    Enhanced DecimalField that includes currency information in the response.

    This field serializes monetary values as an object with both the amount and currency:
    {
        "amount": 1000.00,
        "currency": "KES",
        "formatted": "KSh 1,000.00"
    }

    Usage in serializers:
        class InvoiceSerializer(serializers.ModelSerializer):
            total = MoneyField(max_digits=15, decimal_places=2, source_currency='KES')
            # OR dynamically from instance:
            total = MoneyField(max_digits=15, decimal_places=2, currency_field='currency')

    Parameters:
        source_currency (str): Static currency code (e.g., 'KES', 'USD')
        currency_field (str): Name of the field on the instance that contains the currency
        simple_mode (bool): If True, returns just the decimal value (legacy compatibility)
    """

    def __init__(self, *args, **kwargs):
        # Custom parameters
        self.source_currency = kwargs.pop('source_currency', None)
        self.currency_field = kwargs.pop('currency_field', None)
        self.simple_mode = kwargs.pop('simple_mode', False)

        # Standard DecimalField initialization
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        """Convert value to enhanced money representation"""
        # Get the decimal value first
        decimal_value = super().to_representation(value)

        # Simple mode: return just the number (backward compatible)
        if self.simple_mode:
            return decimal_value

        # Determine currency
        currency = self._get_currency()

        # Format the value
        formatted = self._format_currency(decimal_value, currency)

        # Return enhanced representation
        return {
            'amount': decimal_value,
            'currency': currency,
            'formatted': formatted
        }

    def _get_currency(self):
        """Determine the currency for this field"""
        # Priority 1: Static source_currency
        if self.source_currency:
            return self.source_currency

        # Priority 2: Dynamic currency_field from instance
        if self.currency_field and hasattr(self.parent, 'instance'):
            instance = self.parent.instance
            if instance:
                currency = getattr(instance, self.currency_field, None)
                if currency:
                    return currency

        # Priority 3: Check if parent has currency field
        if hasattr(self.parent, 'instance'):
            instance = self.parent.instance
            if instance and hasattr(instance, 'currency'):
                return instance.currency

        # Fallback: Default to KES
        return 'KES'

    def _format_currency(self, value, currency):
        """Format currency value with symbol"""
        if value is None:
            return None

        # Currency symbols
        SYMBOLS = {
            'KES': 'KSh', 'USD': '$', 'EUR': '€', 'GBP': '£',
            'UGX': 'USh', 'TZS': 'TSh', 'ZAR': 'R', 'NGN': '₦',
            'GHS': 'GH₵', 'RWF': 'FRw', 'ETB': 'Br', 'AED': 'د.إ',
            'INR': '₹', 'CNY': '¥', 'JPY': '¥'
        }

        # Decimal places per currency
        DECIMALS = {
            'KES': 2, 'USD': 2, 'EUR': 2, 'GBP': 2, 'UGX': 0,
            'TZS': 0, 'ZAR': 2, 'NGN': 2, 'GHS': 2, 'RWF': 0,
            'ETB': 2, 'AED': 2, 'INR': 2, 'CNY': 2, 'JPY': 0
        }

        symbol = SYMBOLS.get(currency, currency)
        decimals = DECIMALS.get(currency, 2)

        try:
            num_value = float(value)
            formatted_num = f"{num_value:,.{decimals}f}"

            # Symbol placement
            if currency in ['USD', 'GBP', 'EUR']:
                return f"{symbol}{formatted_num}"
            return f"{symbol} {formatted_num}"
        except (ValueError, TypeError):
            return f"{symbol} {value}"


class ConditionalMoneyField(serializers.SerializerMethodField):
    """
    Alternative approach: Use SerializerMethodField for complete control.

    This gives you full flexibility to customize the money representation
    in a method on your serializer.

    Usage:
        class InvoiceSerializer(serializers.ModelSerializer):
            total_display = ConditionalMoneyField()

            def get_total_display(self, obj):
                return format_money(obj.total, obj.currency)
    """
    pass


def format_money(amount, currency='KES'):
    """
    Standalone helper function to format money values.
    Can be used in serializers, views, or templates.

    Args:
        amount: Decimal or float amount
        currency: ISO 4217 currency code

    Returns:
        dict: { 'amount': Decimal, 'currency': str, 'formatted': str }
    """
    # Currency symbols
    SYMBOLS = {
        'KES': 'KSh', 'USD': '$', 'EUR': '€', 'GBP': '£',
        'UGX': 'USh', 'TZS': 'TSh', 'ZAR': 'R', 'NGN': '₦',
        'GHS': 'GH₵', 'RWF': 'FRw', 'ETB': 'Br', 'AED': 'د.إ',
        'INR': '₹', 'CNY': '¥', 'JPY': '¥'
    }

    # Decimal places per currency
    DECIMALS = {
        'KES': 2, 'USD': 2, 'EUR': 2, 'GBP': 2, 'UGX': 0,
        'TZS': 0, 'ZAR': 2, 'NGN': 2, 'GHS': 2, 'RWF': 0,
        'ETB': 2, 'AED': 2, 'INR': 2, 'CNY': 2, 'JPY': 0
    }

    symbol = SYMBOLS.get(currency, currency)
    decimals = DECIMALS.get(currency, 2)

    try:
        if amount is None:
            amount = Decimal('0.00')

        num_value = float(amount)
        formatted_num = f"{num_value:,.{decimals}f}"

        # Symbol placement
        if currency in ['USD', 'GBP', 'EUR']:
            formatted = f"{symbol}{formatted_num}"
        else:
            formatted = f"{symbol} {formatted_num}"

        return {
            'amount': amount,
            'currency': currency,
            'formatted': formatted
        }
    except (ValueError, TypeError) as e:
        return {
            'amount': amount,
            'currency': currency,
            'formatted': f"{symbol} {amount}",
            'error': str(e)
        }
