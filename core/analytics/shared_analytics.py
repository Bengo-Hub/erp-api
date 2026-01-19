"""
Shared Analytics Utilities

Provides common analytics functions used across multiple modules (executive dashboard,
finance dashboard, reports, etc.) to ensure consistent data calculations.

CRITICAL: All financial calculations use multi-currency conversion to KES for accurate reporting.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Count, Avg, Q
from django.db.models.functions import TruncMonth, TruncWeek
import logging

from core.analytics.currency_converter import AnalyticsCurrencyConverter

logger = logging.getLogger(__name__)


class SharedAnalyticsService:
    """
    Centralized service for analytics calculations used by multiple modules.
    Ensures consistent data across executive dashboard, finance dashboard, and reports.
    """

    @staticmethod
    def get_date_range(period='month'):
        """
        Get start and end dates for a given period.

        Args:
            period: 'week', 'month', 'quarter', or 'year'

        Returns:
            tuple: (start_date, end_date)
        """
        end_date = timezone.now().date()
        period_days = {
            'week': 7,
            'month': 30,
            'quarter': 90,
            'year': 365
        }
        days = period_days.get(period, 30)
        start_date = end_date - timedelta(days=days)
        return start_date, end_date

    @staticmethod
    def get_revenue(start_date, end_date, business_id=None):
        """
        Calculate total revenue for a date range with multi-currency conversion to KES.

        Revenue is calculated from incoming payments (direction='in').
        All payments are converted to KES using their recorded exchange rates.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            Decimal: Total revenue amount in KES
        """
        try:
            from finance.payment.models import Payment

            queryset = Payment.objects.filter(
                payment_date__gte=start_date,
                payment_date__lte=end_date,
                direction='in'
            )

            if business_id:
                # Include payments for the business OR payments without a branch assigned
                queryset = queryset.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            # Convert all payments to KES using currency converter
            converter = AnalyticsCurrencyConverter(base_currency='KES')
            total_kes = converter.convert_queryset_aggregate(
                queryset,
                amount_field='amount',
                currency_field='currency',
                default_currency='KES'
            )

            return total_kes

        except ImportError as e:
            logger.error(f"Payment module not available: {e}")
            return Decimal('0')
        except Exception as e:
            logger.error(f"Error calculating revenue: {e}")
            return Decimal('0')

    @staticmethod
    def get_expenses(start_date, end_date, business_id=None):
        """
        Calculate total expenses for a date range with multi-currency conversion to KES.

        All expenses are converted to KES using their recorded exchange rates.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            Decimal: Total expenses amount in KES
        """
        try:
            from finance.expenses.models import Expense

            queryset = Expense.objects.filter(
                date_added__gte=start_date,
                date_added__lte=end_date
            )

            if business_id:
                # Include expenses for the business OR expenses without a branch assigned
                queryset = queryset.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            # Convert all expenses to KES using currency converter
            converter = AnalyticsCurrencyConverter(base_currency='KES')
            total_kes = converter.convert_queryset_aggregate(
                queryset,
                amount_field='total_amount',
                currency_field='currency',
                default_currency='KES'
            )

            return total_kes

        except ImportError as e:
            logger.error(f"Expense module not available: {e}")
            return Decimal('0')
        except Exception as e:
            logger.error(f"Error calculating expenses: {e}")
            return Decimal('0')

    @staticmethod
    def get_net_profit(start_date, end_date, business_id=None):
        """
        Calculate net profit (revenue - expenses) for a date range.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            Decimal: Net profit amount
        """
        revenue = SharedAnalyticsService.get_revenue(start_date, end_date, business_id)
        expenses = SharedAnalyticsService.get_expenses(start_date, end_date, business_id)
        return revenue - expenses

    @staticmethod
    def get_profit_margin(start_date, end_date, business_id=None):
        """
        Calculate profit margin percentage for a date range.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            float: Profit margin percentage
        """
        revenue = SharedAnalyticsService.get_revenue(start_date, end_date, business_id)
        if revenue <= 0:
            return 0.0

        net_profit = SharedAnalyticsService.get_net_profit(start_date, end_date, business_id)
        return float(net_profit / revenue * 100)

    @staticmethod
    def get_financial_summary(start_date, end_date, business_id=None):
        """
        Get comprehensive financial summary for a date range.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            dict: Financial summary with revenue, expenses, profit, margin
        """
        revenue = SharedAnalyticsService.get_revenue(start_date, end_date, business_id)
        expenses = SharedAnalyticsService.get_expenses(start_date, end_date, business_id)
        net_profit = revenue - expenses
        profit_margin = float(net_profit / revenue * 100) if revenue > 0 else 0.0

        return {
            'total_revenue': float(revenue),
            'total_expenses': float(expenses),
            'net_profit': float(net_profit),
            'profit_margin': round(profit_margin, 2)
        }

    @staticmethod
    def get_order_count(start_date, end_date, business_id=None, status=None):
        """
        Get count of orders for a date range.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by
            status: Optional order status filter

        Returns:
            int: Order count
        """
        try:
            from core_orders.models import BaseOrder

            queryset = BaseOrder.objects.filter(
                order_date__gte=start_date,
                order_date__lte=end_date
            )

            if business_id:
                # Include orders for the business OR orders without a branch assigned
                queryset = queryset.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            if status:
                queryset = queryset.filter(status=status)

            return queryset.count()

        except ImportError as e:
            logger.error(f"Orders module not available: {e}")
            return 0
        except Exception as e:
            logger.error(f"Error counting orders: {e}")
            return 0

    @staticmethod
    def get_customer_count(start_date=None, end_date=None, business_id=None, new_only=False):
        """
        Get count of customers.

        Args:
            start_date: Optional start date for new customers
            end_date: Optional end date for new customers
            business_id: Optional business ID to filter by
            new_only: If True, count only customers added in date range

        Returns:
            int: Customer count
        """
        try:
            from crm.contacts.models import Contact

            queryset = Contact.objects.filter(
                contact_type='Customers',
                is_deleted=False
            )

            if business_id:
                # Include customers for the business OR customers without a business assigned
                queryset = queryset.filter(
                    Q(business=business_id) | Q(business__isnull=True)
                )

            if new_only and start_date and end_date:
                queryset = queryset.filter(
                    added_on__gte=start_date,
                    added_on__lte=end_date
                )

            return queryset.count()

        except ImportError as e:
            logger.error(f"CRM module not available: {e}")
            return 0
        except Exception as e:
            logger.error(f"Error counting customers: {e}")
            return 0

    @staticmethod
    def get_employee_count(business_id=None, active_only=True):
        """
        Get count of employees.

        Args:
            business_id: Optional business ID to filter by
            active_only: If True, count only non-terminated employees

        Returns:
            int: Employee count
        """
        try:
            from hrm.employees.models import Employee

            queryset = Employee.objects.filter(deleted=False)

            if active_only:
                queryset = queryset.filter(terminated=False)

            if business_id:
                # Include employees for the business OR employees without a business assigned
                queryset = queryset.filter(
                    Q(business_id=business_id) | Q(business__isnull=True)
                )

            return queryset.count()

        except ImportError as e:
            logger.error(f"HRM module not available: {e}")
            return 0
        except Exception as e:
            logger.error(f"Error counting employees: {e}")
            return 0

    @staticmethod
    def get_supplier_count(business_id=None):
        """
        Get count of suppliers.

        Args:
            business_id: Optional business ID to filter by

        Returns:
            int: Supplier count
        """
        try:
            from crm.contacts.models import Contact

            queryset = Contact.objects.filter(
                contact_type='Suppliers',
                is_deleted=False
            )

            if business_id:
                # Include suppliers for the business OR suppliers without a business assigned
                queryset = queryset.filter(
                    Q(business=business_id) | Q(business__isnull=True)
                )

            return queryset.count()

        except ImportError as e:
            logger.error(f"CRM module not available: {e}")
            return 0
        except Exception as e:
            logger.error(f"Error counting suppliers: {e}")
            return 0

    @staticmethod
    def get_order_fulfillment_rate(start_date, end_date, business_id=None):
        """
        Calculate order fulfillment rate for a date range.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            float: Fulfillment rate (0-1)
        """
        total = SharedAnalyticsService.get_order_count(start_date, end_date, business_id)
        if total == 0:
            return 0.0

        completed = SharedAnalyticsService.get_order_count(
            start_date, end_date, business_id, status='completed'
        )
        return round(completed / total, 4)

    @staticmethod
    def get_revenue_trends(start_date, end_date, business_id=None):
        """
        Get revenue trend data for charts.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            list: List of {'period': str, 'value': float} dicts
        """
        try:
            from finance.payment.models import Payment

            # Determine truncation based on date range
            days_diff = (end_date - start_date).days
            if days_diff <= 14:
                trunc_func = TruncWeek
                date_format = '%b %d'
            else:
                trunc_func = TruncMonth
                date_format = '%b %Y'

            queryset = Payment.objects.filter(
                payment_date__gte=start_date,
                payment_date__lte=end_date,
                direction='in'
            )

            if business_id:
                # Include payments for the business OR payments without a branch assigned
                queryset = queryset.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            by_period = queryset.annotate(
                period_date=trunc_func('payment_date')
            ).values('period_date').annotate(
                value=Sum('amount')
            ).order_by('period_date')

            return [
                {'period': r['period_date'].strftime(date_format), 'value': float(r['value'] or 0)}
                for r in by_period
            ]

        except ImportError:
            return []
        except Exception as e:
            logger.error(f"Error getting revenue trends: {e}")
            return []

    @staticmethod
    def get_expense_trends(start_date, end_date, business_id=None):
        """
        Get expense trend data for charts.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            list: List of {'period': str, 'value': float} dicts
        """
        try:
            from finance.expenses.models import Expense

            # Determine truncation based on date range
            days_diff = (end_date - start_date).days
            if days_diff <= 14:
                trunc_func = TruncWeek
                date_format = '%b %d'
            else:
                trunc_func = TruncMonth
                date_format = '%b %Y'

            queryset = Expense.objects.filter(
                date_added__gte=start_date,
                date_added__lte=end_date
            )

            if business_id:
                # Include expenses for the business OR expenses without a branch assigned
                queryset = queryset.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            by_period = queryset.annotate(
                period_date=trunc_func('date_added')
            ).values('period_date').annotate(
                value=Sum('total_amount')
            ).order_by('period_date')

            return [
                {'period': e['period_date'].strftime(date_format), 'value': float(e['value'] or 0)}
                for e in by_period
            ]

        except ImportError:
            return []
        except Exception as e:
            logger.error(f"Error getting expense trends: {e}")
            return []

    @staticmethod
    def get_profit_trends(start_date, end_date, business_id=None):
        """
        Get profit trend data for charts.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            list: List of {'period': str, 'value': float} dicts
        """
        revenue_trends = SharedAnalyticsService.get_revenue_trends(start_date, end_date, business_id)
        expense_trends = SharedAnalyticsService.get_expense_trends(start_date, end_date, business_id)

        revenue_dict = {r['period']: r['value'] for r in revenue_trends}
        expense_dict = {e['period']: e['value'] for e in expense_trends}

        all_periods = sorted(set(list(revenue_dict.keys()) + list(expense_dict.keys())))

        return [
            {'period': p, 'value': revenue_dict.get(p, 0) - expense_dict.get(p, 0)}
            for p in all_periods
        ]

    @staticmethod
    def get_customer_growth(start_date, end_date, business_id=None):
        """
        Get customer growth trend data for charts.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            list: List of {'period': str, 'value': int} dicts
        """
        try:
            from crm.contacts.models import Contact

            # Determine truncation based on date range
            days_diff = (end_date - start_date).days
            if days_diff <= 14:
                trunc_func = TruncWeek
                date_format = '%b %d'
            else:
                trunc_func = TruncMonth
                date_format = '%b %Y'

            queryset = Contact.objects.filter(
                contact_type='Customers',
                added_on__gte=start_date,
                added_on__lte=end_date
            )

            if business_id:
                # Include customers for the business OR customers without a business assigned
                queryset = queryset.filter(
                    Q(business=business_id) | Q(business__isnull=True)
                )

            by_period = queryset.annotate(
                period_date=trunc_func('added_on')
            ).values('period_date').annotate(
                value=Count('id')
            ).order_by('period_date')

            return [
                {'period': c['period_date'].strftime(date_format), 'value': int(c['value'] or 0)}
                for c in by_period
            ]

        except ImportError:
            return []
        except Exception as e:
            logger.error(f"Error getting customer growth: {e}")
            return []

    @staticmethod
    def get_order_trends(start_date, end_date, business_id=None):
        """
        Get order trend data for charts.

        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by

        Returns:
            list: List of {'period': str, 'value': int} dicts
        """
        try:
            from core_orders.models import BaseOrder

            # Determine truncation based on date range
            days_diff = (end_date - start_date).days
            if days_diff <= 14:
                trunc_func = TruncWeek
                date_format = '%b %d'
            else:
                trunc_func = TruncMonth
                date_format = '%b %Y'

            queryset = BaseOrder.objects.filter(
                order_date__gte=start_date,
                order_date__lte=end_date
            )

            if business_id:
                # Include orders for the business OR orders without a branch assigned
                queryset = queryset.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            by_period = queryset.annotate(
                period_date=trunc_func('order_date')
            ).values('period_date').annotate(
                value=Count('id')
            ).order_by('period_date')

            return [
                {'period': o['period_date'].strftime(date_format), 'value': int(o['value'] or 0)}
                for o in by_period
            ]

        except ImportError:
            return []
        except Exception as e:
            logger.error(f"Error getting order trends: {e}")
            return []

    @staticmethod
    def get_outstanding_invoices(business_id=None):
        """
        Get total outstanding invoice amount.

        Args:
            business_id: Optional business ID to filter by

        Returns:
            Decimal: Total outstanding amount
        """
        try:
            from finance.invoicing.models import Invoice

            queryset = Invoice.objects.filter(balance_due__gt=0)

            if business_id:
                # Include invoices for the business OR invoices without a branch assigned
                queryset = queryset.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            total = queryset.aggregate(total=Sum('balance_due'))['total']
            return Decimal(str(total)) if total else Decimal('0')

        except ImportError:
            return Decimal('0')
        except Exception as e:
            logger.error(f"Error getting outstanding invoices: {e}")
            return Decimal('0')

    @staticmethod
    def get_overdue_payments(business_id=None):
        """
        Get total overdue payment amount.

        Args:
            business_id: Optional business ID to filter by

        Returns:
            Decimal: Total overdue amount
        """
        try:
            from finance.invoicing.models import Invoice

            queryset = Invoice.objects.filter(
                balance_due__gt=0,
                due_date__lt=timezone.now().date()
            )

            if business_id:
                # Include invoices for the business OR invoices without a branch assigned
                queryset = queryset.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            total = queryset.aggregate(total=Sum('balance_due'))['total']
            return Decimal(str(total)) if total else Decimal('0')

        except ImportError:
            return Decimal('0')
        except Exception as e:
            logger.error(f"Error getting overdue payments: {e}")
            return Decimal('0')
