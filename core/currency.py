"""
Multi-Currency Support Module
Provides centralized currency handling for the ERP system.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Tuple
from django.conf import settings
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)


# ISO 4217 Currency Definitions
# Priority currencies: KES, USD, EUR (as per user requirements)
CURRENCY_DEFINITIONS = {
    # Priority currencies
    'KES': {'name': 'Kenya Shilling', 'symbol': 'KSh', 'decimal_places': 2, 'priority': 1},
    'USD': {'name': 'US Dollar', 'symbol': '$', 'decimal_places': 2, 'priority': 2},
    'EUR': {'name': 'Euro', 'symbol': '€', 'decimal_places': 2, 'priority': 3},
    # Additional currencies
    'GBP': {'name': 'British Pound', 'symbol': '£', 'decimal_places': 2, 'priority': 4},
    'UGX': {'name': 'Uganda Shilling', 'symbol': 'USh', 'decimal_places': 0, 'priority': 5},
    'TZS': {'name': 'Tanzania Shilling', 'symbol': 'TSh', 'decimal_places': 0, 'priority': 6},
    'ZAR': {'name': 'South African Rand', 'symbol': 'R', 'decimal_places': 2, 'priority': 7},
    'NGN': {'name': 'Nigerian Naira', 'symbol': '₦', 'decimal_places': 2, 'priority': 8},
    'GHS': {'name': 'Ghana Cedi', 'symbol': 'GH₵', 'decimal_places': 2, 'priority': 9},
    'RWF': {'name': 'Rwanda Franc', 'symbol': 'FRw', 'decimal_places': 0, 'priority': 10},
    'ETB': {'name': 'Ethiopian Birr', 'symbol': 'Br', 'decimal_places': 2, 'priority': 11},
    'AED': {'name': 'UAE Dirham', 'symbol': 'د.إ', 'decimal_places': 2, 'priority': 12},
    'INR': {'name': 'Indian Rupee', 'symbol': '₹', 'decimal_places': 2, 'priority': 13},
    'CNY': {'name': 'Chinese Yuan', 'symbol': '¥', 'decimal_places': 2, 'priority': 14},
    'JPY': {'name': 'Japanese Yen', 'symbol': '¥', 'decimal_places': 0, 'priority': 15},
}

# Default currency (Kenya Shilling)
DEFAULT_CURRENCY = 'KES'

# Priority currencies for quick selection
PRIORITY_CURRENCIES = ['KES', 'USD', 'EUR']


class CurrencyService:
    """
    Centralized currency service for multi-currency operations.
    Provides formatting, conversion, and validation.
    """

    @staticmethod
    def get_all_currencies() -> Dict[str, dict]:
        """Get all available currencies sorted by priority."""
        return dict(sorted(
            CURRENCY_DEFINITIONS.items(),
            key=lambda x: x[1].get('priority', 999)
        ))

    @staticmethod
    def get_priority_currencies() -> Dict[str, dict]:
        """Get only priority currencies (KES, USD, EUR)."""
        return {k: v for k, v in CURRENCY_DEFINITIONS.items() if k in PRIORITY_CURRENCIES}

    @staticmethod
    def get_currency_info(currency_code: str) -> Optional[dict]:
        """Get currency information by code."""
        return CURRENCY_DEFINITIONS.get(currency_code.upper())

    @staticmethod
    def is_valid_currency(currency_code: str) -> bool:
        """Check if a currency code is valid."""
        return currency_code.upper() in CURRENCY_DEFINITIONS

    @staticmethod
    def get_symbol(currency_code: str) -> str:
        """Get currency symbol."""
        info = CURRENCY_DEFINITIONS.get(currency_code.upper(), {})
        return info.get('symbol', currency_code)

    @staticmethod
    def get_decimal_places(currency_code: str) -> int:
        """Get decimal places for a currency."""
        info = CURRENCY_DEFINITIONS.get(currency_code.upper(), {})
        return info.get('decimal_places', 2)

    @staticmethod
    def format_amount(
        amount: Decimal,
        currency_code: str = DEFAULT_CURRENCY,
        include_symbol: bool = True,
        locale: str = 'en'
    ) -> str:
        """
        Format an amount with currency symbol and proper decimal places.

        Args:
            amount: The decimal amount to format
            currency_code: ISO 4217 currency code
            include_symbol: Whether to include the currency symbol
            locale: Locale for number formatting

        Returns:
            Formatted string like "KSh 1,234.56" or "1,234.56 KES"
        """
        currency_code = currency_code.upper()
        info = CURRENCY_DEFINITIONS.get(currency_code, {})
        decimal_places = info.get('decimal_places', 2)
        symbol = info.get('symbol', currency_code)

        # Round to proper decimal places
        quantize_str = '0.' + '0' * decimal_places if decimal_places > 0 else '1'
        rounded_amount = Decimal(str(amount)).quantize(
            Decimal(quantize_str),
            rounding=ROUND_HALF_UP
        )

        # Format with thousand separators
        if decimal_places > 0:
            formatted = f"{rounded_amount:,.{decimal_places}f}"
        else:
            formatted = f"{int(rounded_amount):,}"

        if include_symbol:
            # Symbol placement based on currency convention
            if currency_code in ['USD', 'GBP', 'EUR']:
                return f"{symbol}{formatted}"
            else:
                return f"{symbol} {formatted}"

        return formatted

    @staticmethod
    def parse_amount(
        value: str,
        currency_code: str = DEFAULT_CURRENCY
    ) -> Decimal:
        """
        Parse a formatted currency string to Decimal.

        Args:
            value: String like "KSh 1,234.56" or "1234.56"
            currency_code: Currency code for context

        Returns:
            Decimal value
        """
        # Remove currency symbols and whitespace
        cleaned = value
        for curr_code, info in CURRENCY_DEFINITIONS.items():
            cleaned = cleaned.replace(info['symbol'], '')
        cleaned = cleaned.replace(',', '').strip()

        try:
            return Decimal(cleaned)
        except Exception:
            return Decimal('0.00')

    @staticmethod
    def round_amount(
        amount: Decimal,
        currency_code: str = DEFAULT_CURRENCY
    ) -> Decimal:
        """Round amount to proper decimal places for currency."""
        decimal_places = CurrencyService.get_decimal_places(currency_code)
        quantize_str = '0.' + '0' * decimal_places if decimal_places > 0 else '1'
        return Decimal(str(amount)).quantize(
            Decimal(quantize_str),
            rounding=ROUND_HALF_UP
        )

    @classmethod
    def convert(
        cls,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        rate: Optional[Decimal] = None
    ) -> Tuple[Decimal, Decimal]:
        """
        Convert amount from one currency to another.

        Args:
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency code
            rate: Exchange rate (if None, will try to fetch)

        Returns:
            Tuple of (converted_amount, rate_used)
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        if from_currency == to_currency:
            return amount, Decimal('1.0000')

        if rate is None:
            rate = cls.get_exchange_rate(from_currency, to_currency)

        converted = amount * rate
        converted = cls.round_amount(converted, to_currency)

        return converted, rate

    @classmethod
    def get_exchange_rate(
        cls,
        from_currency: str,
        to_currency: str
    ) -> Decimal:
        """
        Get exchange rate between two currencies.

        Note: In production, this should integrate with an exchange rate API.
        For now, returns cached rates or defaults.

        Args:
            from_currency: Source currency code
            to_currency: Target currency code

        Returns:
            Exchange rate as Decimal
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        if from_currency == to_currency:
            return Decimal('1.0000')

        # Try to get from cache
        cache_key = f"exchange_rate:{from_currency}:{to_currency}"
        cached_rate = cache.get(cache_key)
        if cached_rate:
            return Decimal(str(cached_rate))

        # Try to get from database
        try:
            from core.models import ExchangeRate
            rate_obj = ExchangeRate.objects.filter(
                from_currency=from_currency,
                to_currency=to_currency,
                is_active=True
            ).order_by('-effective_date').first()

            if rate_obj:
                # Cache for 1 hour
                cache.set(cache_key, str(rate_obj.rate), 3600)
                return rate_obj.rate
        except Exception as e:
            logger.warning(f"Could not fetch exchange rate from DB: {e}")

        # Return 1.0 as fallback (no conversion)
        logger.warning(f"No exchange rate found for {from_currency} to {to_currency}, using 1.0")
        return Decimal('1.0000')

    @staticmethod
    def get_currency_choices() -> list:
        """
        Get currency choices for Django model fields.

        Returns:
            List of tuples [(code, name), ...]
        """
        return [
            (code, f"{info['name']} ({code})")
            for code, info in sorted(
                CURRENCY_DEFINITIONS.items(),
                key=lambda x: x[1].get('priority', 999)
            )
        ]

    @staticmethod
    def get_priority_currency_choices() -> list:
        """Get priority currency choices only."""
        return [
            (code, f"{CURRENCY_DEFINITIONS[code]['name']} ({code})")
            for code in PRIORITY_CURRENCIES
        ]


# Convenience functions for direct import
def format_currency(amount: Decimal, currency: str = DEFAULT_CURRENCY, **kwargs) -> str:
    """Shortcut for CurrencyService.format_amount"""
    return CurrencyService.format_amount(amount, currency, **kwargs)


def convert_currency(
    amount: Decimal,
    from_curr: str,
    to_curr: str,
    rate: Optional[Decimal] = None
) -> Tuple[Decimal, Decimal]:
    """Shortcut for CurrencyService.convert"""
    return CurrencyService.convert(amount, from_curr, to_curr, rate)


def get_currency_symbol(currency: str) -> str:
    """Shortcut for CurrencyService.get_symbol"""
    return CurrencyService.get_symbol(currency)


def validate_currency(currency: str) -> bool:
    """Shortcut for CurrencyService.is_valid_currency"""
    return CurrencyService.is_valid_currency(currency)
