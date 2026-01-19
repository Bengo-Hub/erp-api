"""
Currency Conversion Helper for Analytics

Provides utilities to convert financial data to a base currency for accurate analytics.
All analytics should use these helpers to ensure consistent multi-currency support.
"""
from decimal import Decimal
from typing import List, Dict, Any, Optional
from django.db.models import QuerySet, F, Case, When, DecimalField, Value
from django.db.models.functions import Coalesce
import logging

from core.currency import CurrencyService, DEFAULT_CURRENCY

logger = logging.getLogger(__name__)


class AnalyticsCurrencyConverter:
    """
    Helper class for converting financial data to base currency in analytics queries.

    Usage:
        # For simple conversion
        converter = AnalyticsCurrencyConverter(base_currency='KES')
        converted_amount = converter.convert_amount(100, 'USD', 'KES')

        # For queryset annotation
        queryset = Payment.objects.all()
        queryset = converter.annotate_converted_amount(
            queryset,
            amount_field='amount',
            currency_field='currency'
        )
    """

    def __init__(self, base_currency: str = DEFAULT_CURRENCY):
        """
        Initialize converter with a base currency.

        Args:
            base_currency: Target currency for all conversions (default: KES)
        """
        self.base_currency = base_currency.upper()
        self._rate_cache = {}

    def convert_amount(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: Optional[str] = None
    ) -> Decimal:
        """
        Convert a single amount from one currency to another.

        Args:
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency (defaults to base_currency)

        Returns:
            Converted amount as Decimal
        """
        if to_currency is None:
            to_currency = self.base_currency

        if not amount or amount == 0:
            return Decimal('0.00')

        # Use CurrencyService for conversion
        converted, rate = CurrencyService.convert(
            amount=Decimal(str(amount)),
            from_currency=from_currency,
            to_currency=to_currency
        )

        return converted

    def convert_queryset_aggregate(
        self,
        queryset: QuerySet,
        amount_field: str,
        currency_field: str,
        default_currency: str = DEFAULT_CURRENCY
    ) -> Decimal:
        """
        Convert and sum amounts from a queryset with multiple currencies.

        This method:
        1. Groups by currency
        2. Sums amounts per currency
        3. Converts each sum to base currency
        4. Returns total in base currency

        Args:
            queryset: Django queryset containing financial records
            amount_field: Name of the amount field (e.g., 'amount', 'total')
            currency_field: Name of the currency field (e.g., 'currency')
            default_currency: Fallback currency if currency_field is null

        Returns:
            Total amount converted to base currency

        Example:
            >>> payments = Payment.objects.filter(payment_date__gte=start_date)
            >>> total_kes = converter.convert_queryset_aggregate(
            ...     payments,
            ...     'amount',
            ...     'currency'
            ... )
        """
        from django.db.models import Sum

        try:
            # Group by currency and sum
            currency_totals = queryset.values(currency_field).annotate(
                total=Sum(amount_field)
            )

            total_in_base = Decimal('0.00')

            for row in currency_totals:
                currency = row.get(currency_field) or default_currency
                amount = row.get('total') or Decimal('0.00')

                if amount > 0:
                    converted = self.convert_amount(amount, currency, self.base_currency)
                    total_in_base += converted
                    logger.debug(
                        f"Converted {amount} {currency} to {converted} {self.base_currency}"
                    )

            return total_in_base

        except Exception as e:
            logger.error(f"Error converting queryset aggregate: {e}")
            return Decimal('0.00')

    def convert_list_of_records(
        self,
        records: List[Dict[str, Any]],
        amount_field: str,
        currency_field: str,
        default_currency: str = DEFAULT_CURRENCY
    ) -> Decimal:
        """
        Convert and sum amounts from a list of dictionaries.

        Useful for already-fetched data or manual aggregations.

        Args:
            records: List of dicts containing amount and currency
            amount_field: Key for amount in each dict
            currency_field: Key for currency in each dict
            default_currency: Fallback if currency is missing

        Returns:
            Total amount in base currency
        """
        total = Decimal('0.00')

        for record in records:
            amount = record.get(amount_field, 0)
            currency = record.get(currency_field) or default_currency

            if amount:
                converted = self.convert_amount(Decimal(str(amount)), currency)
                total += converted

        return total

    def annotate_converted_amount(
        self,
        queryset: QuerySet,
        amount_field: str,
        currency_field: str,
        output_field_name: str = 'converted_amount',
        default_currency: str = DEFAULT_CURRENCY
    ) -> QuerySet:
        """
        Annotate a queryset with a converted amount field.

        WARNING: This method uses database-level conversion which may not
        support all currency pairs. For accurate results, consider using
        convert_queryset_aggregate() instead.

        Args:
            queryset: Django queryset
            amount_field: Name of amount field
            currency_field: Name of currency field
            output_field_name: Name for the annotated field
            default_currency: Fallback currency

        Returns:
            QuerySet with annotated converted amount
        """
        from core.models import ExchangeRate
        from django.db.models import Subquery, OuterRef

        # Get exchange rates as subquery
        rate_subquery = ExchangeRate.objects.filter(
            from_currency=Coalesce(F(currency_field), Value(default_currency)),
            to_currency=self.base_currency,
            is_active=True
        ).order_by('-effective_date').values('rate')[:1]

        # Annotate with rate and converted amount
        queryset = queryset.annotate(
            _exchange_rate=Coalesce(
                Subquery(rate_subquery, output_field=DecimalField()),
                Value(Decimal('1.0'))
            )
        ).annotate(
            **{output_field_name: F(amount_field) * F('_exchange_rate')}
        )

        return queryset

    def get_conversion_summary(
        self,
        queryset: QuerySet,
        amount_field: str,
        currency_field: str,
        default_currency: str = DEFAULT_CURRENCY
    ) -> Dict[str, Any]:
        """
        Get a detailed summary of currency conversions.

        Returns breakdown by original currency and converted total.

        Args:
            queryset: Django queryset
            amount_field: Amount field name
            currency_field: Currency field name
            default_currency: Fallback currency

        Returns:
            Dict with 'by_currency' list and 'total_converted' amount
        """
        from django.db.models import Sum

        # Group by currency
        currency_totals = queryset.values(currency_field).annotate(
            total=Sum(amount_field),
            count=Count('id')
        )

        breakdown = []
        total_converted = Decimal('0.00')

        for row in currency_totals:
            currency = row.get(currency_field) or default_currency
            amount = row.get('total') or Decimal('0.00')
            count = row.get('count', 0)

            if amount > 0:
                converted = self.convert_amount(amount, currency)
                total_converted += converted

                breakdown.append({
                    'currency': currency,
                    'original_amount': float(amount),
                    'converted_amount': float(converted),
                    'count': count,
                    'exchange_rate': float(converted / amount) if amount > 0 else 1.0
                })

        return {
            'by_currency': breakdown,
            'total_converted': float(total_converted),
            'base_currency': self.base_currency
        }


# Convenience function for quick conversions
def convert_to_base_currency(
    queryset: QuerySet,
    amount_field: str,
    currency_field: str,
    base_currency: str = DEFAULT_CURRENCY,
    default_currency: str = DEFAULT_CURRENCY
) -> Decimal:
    """
    Quick helper to convert and sum a queryset to base currency.

    Example:
        total_kes = convert_to_base_currency(
            Payment.objects.filter(date__gte=start),
            'amount',
            'currency'
        )
    """
    converter = AnalyticsCurrencyConverter(base_currency=base_currency)
    return converter.convert_queryset_aggregate(
        queryset,
        amount_field,
        currency_field,
        default_currency
    )
