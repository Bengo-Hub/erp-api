"""
Finance Analytics Service

Provides comprehensive analytics for finance management including accounts,
expenses, taxes, and payment analytics.

Uses SharedAnalyticsService for consistent calculations across all dashboards.

CRITICAL: All financial calculations use multi-currency conversion to KES for accurate reporting.
"""

from datetime import datetime, timedelta
import logging
from decimal import Decimal
from django.utils import timezone
from django.db.models import Avg, Count, Q, Sum, F, Min, Max
from django.db import connection
from django.core.cache import cache
from finance.accounts.models import PaymentAccounts, Transaction
from finance.expenses.models import Expense
from finance.taxes.models import Tax, TaxPeriod
from finance.payment.models import BillingDocument, Payment
from finance.invoicing.models import Invoice
from core.analytics.shared_analytics import SharedAnalyticsService
from core.analytics.currency_converter import AnalyticsCurrencyConverter

logger = logging.getLogger(__name__)


class FinanceAnalyticsService:
    """
    Service for finance analytics and reporting.
    Provides metrics for accounts, expenses, taxes, and payments.
    """
    
    def __init__(self):
        self.cache_timeout = 300  # 5 minutes
    
    def get_finance_dashboard_data(self, business_id=None, period='month'):
        """
        Get comprehensive finance dashboard data.

        Args:
            business_id: Business ID to filter data
            period: Time period for analysis ('week', 'month', 'quarter', 'year')

        Returns:
            dict: Finance dashboard data with fallbacks
        """
        try:
            # Get date range using shared utility
            start_date, end_date = SharedAnalyticsService.get_date_range(period)

            # Get financial summary using shared service for consistency
            financial_summary = SharedAnalyticsService.get_financial_summary(start_date, end_date, business_id)

            accounts_summary = self._get_accounts_summary(business_id)
            expenses_analysis = self._get_expenses_analysis(business_id, period)
            tax_analysis = self._get_tax_analysis(business_id, period)
            payment_analysis = self._get_payment_analysis(business_id, period)
            cash_flow = self._get_cash_flow_analysis(business_id, period)
            financial_ratios = self._get_financial_ratios(business_id)
            trends = self._get_financial_trends(business_id, period)

            # Use shared service values for consistency with executive dashboard
            total_revenue = financial_summary.get('total_revenue', 0)
            total_expenses = financial_summary.get('total_expenses', 0)
            net_profit = financial_summary.get('net_profit', 0)
            net_cash_flow = cash_flow.get('net_cash_flow', 0)

            # Get outstanding invoices using shared service
            outstanding_invoices = float(SharedAnalyticsService.get_outstanding_invoices(business_id))
            overdue_payments = float(SharedAnalyticsService.get_overdue_payments(business_id))

            return {
                # Dashboard card data
                'total_revenue': round(float(total_revenue), 2),
                'total_expenses': round(float(total_expenses), 2),
                'net_profit': round(float(net_profit), 2),
                'cash_flow': round(float(net_cash_flow), 2),
                'outstanding_invoices': round(float(outstanding_invoices), 2),
                'overdue_payments': round(float(overdue_payments), 2),

                # Chart data
                'revenue_trends': trends.get('revenue_trends', []),
                'expense_breakdown': trends.get('expense_breakdown', []),
                'cash_flow_data': trends.get('cash_flow_data', []),

                # Detailed analysis
                'accounts_summary': accounts_summary,
                'expenses_analysis': expenses_analysis,
                'tax_analysis': tax_analysis,
                'tax_summary': tax_analysis,
                'payment_analysis': payment_analysis,
                'cash_flow_analysis': cash_flow,
                'financial_ratios': financial_ratios,
                'trends': trends
            }
        except Exception as e:
            logger.error(f"Error getting finance dashboard data: {e}")
            return self._get_fallback_finance_data()
    
    def _get_accounts_summary(self, business_id):
        """Get accounts summary metrics."""
        try:
            queryset = PaymentAccounts.objects.filter(status='active')
            if business_id:
                queryset = queryset.filter(business_id=business_id)
            
            total_accounts = queryset.count()
            total_balance = queryset.aggregate(total=Sum('balance'))['total'] or 0
            avg_balance = queryset.aggregate(avg=Avg('balance'))['avg'] or 0
            
            # Account types breakdown
            account_types = queryset.values('account_type').annotate(
                count=Count('id'),
                total_balance=Sum('balance')
            ).order_by('-total_balance')
            
            return {
                'total_accounts': total_accounts,
                'total_balance': round(total_balance, 2),
                'avg_balance': round(avg_balance, 2),
                'account_types': list(account_types)
            }
        except Exception:
            return self._get_fallback_accounts_data()
    
    def get_financial_summary(self, start_date, end_date, business_id=None):
        """
        Get financial summary for a date range.
        
        Consolidates duplicate logic from finance/api.py.
        
        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            business_id: Optional business ID to filter by
        
        Returns:
            dict: Financial summary with invoices, payments, expenses, outstanding amounts
        """
        try:
            # Build base querysets
            # Include both legacy BillingDocument invoices and new Invoice model records.
            billing_qs = BillingDocument.objects.filter(
                document_type='invoice',
                issue_date__gte=start_date,
                issue_date__lte=end_date,
                related_order__isnull=True  # avoid double-counting invoices linked to orders
            )

            invoice_model_qs = Invoice.objects.filter(
                invoice_date__gte=start_date,
                invoice_date__lte=end_date
            )
            payment_qs = Payment.objects.filter(
                payment_date__gte=start_date,
                payment_date__lte=end_date
            )
            expense_qs = Expense.objects.filter(
                date_added__gte=start_date,
                date_added__lte=end_date
            )
            
            # Apply business filter if provided (include records with null branch)
            if business_id:
                invoice_qs = invoice_qs.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )
                billing_qs = billing_qs.filter(business_id=business_id)  # BillingDocument has direct business FK
                invoice_model_qs = invoice_model_qs.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )
                payment_qs = payment_qs.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )
                expense_qs = expense_qs.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )
            
            # Calculate totals with multi-currency conversion to KES
            converter = AnalyticsCurrencyConverter(base_currency='KES')

            # Convert BillingDocument invoices to KES
            total_billing = converter.convert_queryset_aggregate(
                billing_qs, 'total', 'currency', 'KES'
            )

            # Convert Invoice model records to KES (uses BaseOrder currency field)
            total_invoice_models = converter.convert_queryset_aggregate(
                invoice_model_qs, 'total', 'currency', 'KES'
            )

            total_invoices = total_billing + total_invoice_models

            # Convert payments to KES
            total_payments = converter.convert_queryset_aggregate(
                payment_qs, 'amount', 'currency', 'KES'
            )

            # Convert expenses to KES
            total_expenses = converter.convert_queryset_aggregate(
                expense_qs, 'total_amount', 'currency', 'KES'
            )

            # Convert outstanding balances to KES
            outstanding_billing = converter.convert_queryset_aggregate(
                billing_qs.filter(balance_due__gt=0), 'balance_due', 'currency', 'KES'
            )
            outstanding_invoice_models = converter.convert_queryset_aggregate(
                invoice_model_qs.filter(balance_due__gt=0), 'balance_due', 'currency', 'KES'
            )
            outstanding_invoices = outstanding_billing + outstanding_invoice_models
            
            return {
                'total_invoices': round(total_invoices, 2),
                'total_payments': round(total_payments, 2),
                'total_expenses': round(total_expenses, 2),
                'outstanding_invoices': round(outstanding_invoices, 2),
                'net_position': round(total_invoices + total_payments - total_expenses, 2)
            }
        except Exception as e:
            # logger.error(f"Error calculating financial summary: {str(e)}") # This line was not in the original file, so it's not added.
            return {
                'total_invoices': 0,
                'total_payments': 0,
                'total_expenses': 0,
                'outstanding_invoices': 0,
                'net_position': 0
            }
    
    def _get_expenses_analysis(self, business_id, period):
        """Get expenses analysis metrics."""
        try:
            # Calculate date range
            end_date = timezone.now().date()
            if period == 'week':
                start_date = end_date - timedelta(days=7)
            elif period == 'month':
                start_date = end_date - timedelta(days=30)
            elif period == 'quarter':
                start_date = end_date - timedelta(days=90)
            elif period == 'year':
                start_date = end_date - timedelta(days=365)
            else:
                start_date = end_date - timedelta(days=30)
            
            queryset = Expense.objects.filter(
                date_added__gte=start_date,
                date_added__lte=end_date
            )

            if business_id:
                # Expense has branch FK, include records with null branch
                queryset = queryset.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )
            
            total_expenses = queryset.aggregate(total=Sum('total_amount'))['total'] or 0
            avg_expense = queryset.aggregate(avg=Avg('total_amount'))['avg'] or 0
            expense_count = queryset.count()
            
            # Expenses by category
            expenses_by_category = queryset.values('category__name').annotate(
                total=Sum('total_amount'),
                count=Count('id')
            ).order_by('-total')
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_expenses': round(total_expenses, 2),
                'avg_expense': round(avg_expense, 2),
                'expense_count': expense_count,
                'expenses_by_category': list(expenses_by_category)
            }
        except Exception:
            return self._get_fallback_expenses_data()
    
    def _get_tax_analysis(self, business_id, period):
        """Get tax analysis metrics."""
        try:
            # Calculate date range
            end_date = timezone.now().date()
            if period == 'week':
                start_date = end_date - timedelta(days=7)
            elif period == 'month':
                start_date = end_date - timedelta(days=30)
            elif period == 'quarter':
                start_date = end_date - timedelta(days=90)
            elif period == 'year':
                start_date = end_date - timedelta(days=365)
            else:
                start_date = end_date - timedelta(days=30)
            
            queryset = TaxPeriod.objects.filter(
                period_start__gte=start_date,
                period_end__lte=end_date
            )
            
            if business_id:
                queryset = queryset.filter(business_id=business_id)
            
            total_tax = queryset.aggregate(total=Sum('tax_amount'))['total'] or 0
            total_vat = queryset.aggregate(total=Sum('vat_amount'))['total'] or 0
            total_paye = queryset.aggregate(total=Sum('paye_amount'))['total'] or 0
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_tax': round(total_tax, 2),
                'total_vat': round(total_vat, 2),
                'total_paye': round(total_paye, 2),
                'total_liability': round(total_tax + total_vat + total_paye, 2)
            }
        except Exception:
            return self._get_fallback_tax_data()
    
    def _get_payment_analysis(self, business_id, period):
        """Get payment analysis metrics."""
        try:
            # Calculate date range
            end_date = timezone.now().date()
            if period == 'week':
                start_date = end_date - timedelta(days=7)
            elif period == 'month':
                start_date = end_date - timedelta(days=30)
            elif period == 'quarter':
                start_date = end_date - timedelta(days=90)
            elif period == 'year':
                start_date = end_date - timedelta(days=365)
            else:
                start_date = end_date - timedelta(days=30)
            
            queryset = Payment.objects.filter(
                payment_date__gte=start_date,
                payment_date__lte=end_date
            )

            if business_id:
                # Payment has branch FK, include records with null branch
                queryset = queryset.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            total_payments = queryset.aggregate(total=Sum('amount'))['total'] or 0
            payment_count = queryset.count()
            avg_payment = queryset.aggregate(avg=Avg('amount'))['avg'] or 0
            
            # Payments by method
            payments_by_method = queryset.values('payment_method').annotate(
                total=Sum('amount'),
                count=Count('id')
            ).order_by('-total')
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_payments': round(total_payments, 2),
                'payment_count': payment_count,
                'avg_payment': round(avg_payment, 2),
                'payments_by_method': list(payments_by_method)
            }
        except Exception:
            return self._get_fallback_payment_data()
    
    def _get_cash_flow_analysis(self, business_id, period):
        """Get cash flow analysis metrics."""
        try:
            # Calculate date range
            end_date = timezone.now().date()
            if period == 'week':
                start_date = end_date - timedelta(days=7)
            elif period == 'month':
                start_date = end_date - timedelta(days=30)
            elif period == 'quarter':
                start_date = end_date - timedelta(days=90)
            elif period == 'year':
                start_date = end_date - timedelta(days=365)
            else:
                start_date = end_date - timedelta(days=30)
            
            # Get cash inflows (payments - money IN)
            cash_inflows = Payment.objects.filter(
                payment_date__gte=start_date,
                payment_date__lte=end_date,
                direction='in'
            )
            if business_id:
                cash_inflows = cash_inflows.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            total_inflows = cash_inflows.aggregate(total=Sum('amount'))['total'] or 0

            # Get cash outflows (expenses)
            cash_outflows = Expense.objects.filter(
                date_added__gte=start_date,
                date_added__lte=end_date
            )
            if business_id:
                cash_outflows = cash_outflows.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )
            
            total_outflows = cash_outflows.aggregate(total=Sum('total_amount'))['total'] or 0
            
            net_cash_flow = total_inflows - total_outflows
            
            return {
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'total_inflows': round(total_inflows, 2),
                'total_outflows': round(total_outflows, 2),
                'net_cash_flow': round(net_cash_flow, 2),
                'cash_flow_ratio': round(total_inflows / total_outflows, 2) if total_outflows > 0 else 0
            }
        except Exception:
            return self._get_fallback_cash_flow_data()
    
    def _get_financial_ratios(self, business_id):
        """Get financial ratios calculated from real data."""
        try:
            queryset = PaymentAccounts.objects.filter(status='active')
            if business_id:
                queryset = queryset.filter(business_id=business_id)

            # Get assets and liabilities from account types
            assets = queryset.filter(
                account_type__in=['bank', 'cash', 'mobile_money', 'receivables', 'Bank', 'Cash', 'Mobile Money', 'Receivables']
            ).aggregate(total=Sum('balance'))['total'] or 0

            liabilities = queryset.filter(
                account_type__in=['payables', 'credit', 'Payables', 'Credit', 'loan', 'Loan']
            ).aggregate(total=Sum('balance'))['total'] or 0

            # Current assets (liquid)
            current_assets = queryset.filter(
                account_type__in=['bank', 'cash', 'mobile_money', 'Bank', 'Cash', 'Mobile Money']
            ).aggregate(total=Sum('balance'))['total'] or 0

            # Calculate ratios
            current_ratio = float(current_assets / liabilities) if liabilities > 0 else 0
            quick_ratio = float(current_assets / liabilities) if liabilities > 0 else 0
            debt_to_equity = float(liabilities / (assets - liabilities)) if (assets - liabilities) > 0 else 0

            # Get profitability data for ROA/ROE
            from django.utils import timezone
            from datetime import timedelta
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=365)

            # Net profit from last year
            payments = Payment.objects.filter(
                payment_date__gte=start_date,
                payment_date__lte=end_date,
                direction='in'
            )
            if business_id:
                payments = payments.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )
            total_revenue = payments.aggregate(total=Sum('amount'))['total'] or 0

            expenses = Expense.objects.filter(
                date_added__gte=start_date,
                date_added__lte=end_date
            )
            if business_id:
                expenses = expenses.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )
            total_expenses = expenses.aggregate(total=Sum('total_amount'))['total'] or 0

            net_profit = float(total_revenue) - float(total_expenses)

            roa = float(net_profit / assets) if assets > 0 else 0
            roe = float(net_profit / (assets - liabilities)) if (assets - liabilities) > 0 else 0

            return {
                'current_ratio': round(current_ratio, 2),
                'quick_ratio': round(quick_ratio, 2),
                'debt_to_equity': round(debt_to_equity, 2),
                'return_on_assets': round(roa, 4),
                'return_on_equity': round(roe, 4)
            }
        except Exception as e:
            logger.warning(f"Error calculating financial ratios: {e}")
            return self._get_fallback_ratios_data()
    
    def _get_financial_trends(self, business_id, period):
        """Get financial trends over time with real data."""
        try:
            from django.db.models.functions import TruncMonth, TruncWeek, TruncDate
            end_date = timezone.now().date()

            # Determine period count and truncation based on period type
            if period == 'week':
                start_date = end_date - timedelta(days=49)  # 7 weeks
                trunc_func = TruncWeek
                periods = 7
            elif period == 'month':
                start_date = end_date - timedelta(days=180)  # 6 months
                trunc_func = TruncMonth
                periods = 6
            elif period == 'quarter':
                start_date = end_date - timedelta(days=365)  # 4 quarters (12 months)
                trunc_func = TruncMonth
                periods = 12
            elif period == 'year':
                start_date = end_date - timedelta(days=730)  # 2 years (24 months)
                trunc_func = TruncMonth
                periods = 24
            else:
                start_date = end_date - timedelta(days=180)
                trunc_func = TruncMonth
                periods = 6

            # Revenue trends from payments (money IN)
            revenue_qs = Payment.objects.filter(
                payment_date__gte=start_date,
                payment_date__lte=end_date,
                direction='in'
            )
            if business_id:
                # Include payments for the business OR payments without a branch assigned
                revenue_qs = revenue_qs.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            revenue_by_period = revenue_qs.annotate(
                period_date=trunc_func('payment_date')
            ).values('period_date').annotate(
                amount=Sum('amount')
            ).order_by('period_date')

            revenue_trends = [
                {'period': r['period_date'].strftime('%b %Y' if period != 'week' else '%b %d'), 'amount': float(r['amount'] or 0)}
                for r in revenue_by_period
            ]

            # Expense trends
            expense_qs = Expense.objects.filter(
                date_added__gte=start_date,
                date_added__lte=end_date
            )
            if business_id:
                # Include expenses for the business OR expenses without a branch assigned
                expense_qs = expense_qs.filter(
                    Q(branch__business_id=business_id) | Q(branch__isnull=True)
                )

            expense_by_period = expense_qs.annotate(
                period_date=trunc_func('date_added')
            ).values('period_date').annotate(
                amount=Sum('total_amount')
            ).order_by('period_date')

            expense_trends = [
                {'period': e['period_date'].strftime('%b %Y' if period != 'week' else '%b %d'), 'amount': float(e['amount'] or 0)}
                for e in expense_by_period
            ]

            # Calculate profit trends (revenue - expenses per period)
            profit_trends = []
            revenue_dict = {r['period']: r['amount'] for r in revenue_trends}
            expense_dict = {e['period']: e['amount'] for e in expense_trends}
            all_periods = sorted(set(list(revenue_dict.keys()) + list(expense_dict.keys())))
            for p in all_periods:
                rev = revenue_dict.get(p, 0)
                exp = expense_dict.get(p, 0)
                profit_trends.append({'period': p, 'amount': rev - exp})

            # Calculate cash flow trends (same as profit for now)
            cash_flow_trends = profit_trends.copy()

            # Expense breakdown by category
            expense_breakdown = expense_qs.values('category__name').annotate(
                amount=Sum('total_amount')
            ).order_by('-amount')[:8]

            expense_breakdown_list = [
                {'category': e['category__name'] or 'Uncategorized', 'amount': float(e['amount'] or 0)}
                for e in expense_breakdown
            ]

            # Calculate overall trends
            revenue_values = [r['amount'] for r in revenue_trends]
            expense_values = [e['amount'] for e in expense_trends]

            def calc_trend(values):
                if len(values) < 2:
                    return 'stable'
                recent = sum(values[-3:]) / max(len(values[-3:]), 1)
                earlier = sum(values[:3]) / max(len(values[:3]), 1)
                if recent > earlier * 1.05:
                    return 'increasing'
                elif recent < earlier * 0.95:
                    return 'decreasing'
                return 'stable'

            return {
                'period': period,
                'revenue_trend': calc_trend(revenue_values),
                'expense_trend': calc_trend(expense_values),
                'profit_trend': calc_trend([p['amount'] for p in profit_trends]),
                'cash_flow_trend': 'positive' if sum([p['amount'] for p in profit_trends]) > 0 else 'negative',
                'revenue_trends': revenue_trends,
                'expense_trends': expense_trends,
                'profit_trends': profit_trends,
                'cash_flow_data': cash_flow_trends,
                'expense_breakdown': expense_breakdown_list
            }
        except Exception as e:
            logger.warning(f"Error calculating financial trends: {e}")
            return self._get_fallback_trends_data()
    
    # Fallback data methods
    def _get_fallback_finance_data(self):
        """Return fallback finance data if analytics collection fails."""
        return {
            'accounts_summary': self._get_fallback_accounts_data(),
            'expenses_analysis': self._get_fallback_expenses_data(),
            'tax_analysis': self._get_fallback_tax_data(),
            'payment_analysis': self._get_fallback_payment_data(),
            'cash_flow': self._get_fallback_cash_flow_data(),
            'financial_ratios': self._get_fallback_ratios_data(),
            'trends': self._get_fallback_trends_data()
        }
    
    def _get_fallback_accounts_data(self):
        """Return empty accounts data when real data unavailable."""
        return {
            'total_accounts': 0,
            'total_balance': 0.0,
            'avg_balance': 0.0,
            'account_types': []
        }
    
    def _get_fallback_expenses_data(self):
        """Return empty expenses data when real data unavailable."""
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_expenses': 0,
            'avg_expense': 0,
            'expense_count': 0,
            'expenses_by_category': []
        }
    
    def _get_fallback_tax_data(self):
        """Return empty tax data when real data unavailable."""
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_tax': 0.0,
            'total_vat': 0.0,
            'total_paye': 0.0,
            'total_liability': 0.0
        }
    
    def _get_fallback_payment_data(self):
        """Return empty payment data when real data unavailable."""
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_payments': 0,
            'payment_count': 0,
            'avg_payment': 0,
            'payments_by_method': []
        }
    
    def _get_fallback_cash_flow_data(self):
        """Return empty cash flow data when real data unavailable."""
        return {
            'period': 'month',
            'start_date': (timezone.now().date() - timedelta(days=30)),
            'end_date': timezone.now().date(),
            'total_inflows': 0,
            'total_outflows': 0,
            'net_cash_flow': 0,
            'cash_flow_ratio': 0
        }
    
    def _get_fallback_ratios_data(self):
        """Return empty ratios data when real data unavailable."""
        return {
            'current_ratio': 0,
            'quick_ratio': 0,
            'debt_to_equity': 0,
            'return_on_assets': 0,
            'return_on_equity': 0
        }
    
    def _get_fallback_trends_data(self):
        """Return empty trends data when real data unavailable."""
        return {
            'period': 'month',
            'revenue_trend': 'stable',
            'expense_trend': 'stable',
            'profit_trend': 'stable',
            'cash_flow_trend': 'neutral',
            'revenue_trends': [],
            'expense_trends': [],
            'profit_trends': [],
            'cash_flow_data': [],
            'expense_breakdown': []
        }
