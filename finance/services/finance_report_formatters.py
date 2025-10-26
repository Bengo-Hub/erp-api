"""
Finance Report Formatters Service

Modular components for generating professional financial statements with high-performance data aggregation.
Each report type is a single-responsibility class for maintainability and reusability.

Financial Reports Generated:
- Profit & Loss Statement (P&L / Income Statement)
- Balance Sheet (Statement of Financial Position)
- Cash Flow Statement (Direct Method)
- Account Reconciliation
"""

import polars as pl
from decimal import Decimal
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta, date
from django.db.models import Sum, Q, F, Case, When, DecimalField, Count
from django.utils import timezone
import logging

from finance.accounts.models import PaymentAccounts, Transaction
from finance.expenses.models import Expense, ExpenseCategory
from finance.payment.models import BillingDocument, Payment
from finance.taxes.models import Tax

logger = logging.getLogger(__name__)


class ProfitAndLossReport:
    """
    Profit & Loss (P&L) / Income Statement Report.
    
    Structure:
    - Revenue
    - Cost of Goods Sold (COGS)
    - Gross Profit
    - Operating Expenses
    - Operating Income
    - Non-Operating Income/Expenses
    - Pretax Income
    - Taxes
    - Net Income
    """
    
    REPORT_TYPE = 'Profit & Loss Statement'
    
    COLUMNS = [
        {'field': 'line_item', 'header': 'Line Item'},
        {'field': 'description', 'header': 'Description'},
        {'field': 'current_period', 'header': 'Current Period (KShs)'},
        {'field': 'previous_period', 'header': 'Previous Period (KShs)'},
        {'field': 'variance_amount', 'header': 'Variance (KShs)'},
        {'field': 'variance_percent', 'header': 'Variance %'},
    ]
    
    @staticmethod
    def build(start_date: date, end_date: date, business_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Build P&L report for period.
        
        Args:
            start_date: Period start date
            end_date: Period end date
            business_id: Optional business filter
            
        Returns:
            Dict with P&L data, structure, totals, and analysis
        """
        try:
            # Get previous period dates for comparison
            period_days = (end_date - start_date).days
            prev_start = start_date - timedelta(days=period_days + 1)
            prev_end = start_date - timedelta(days=1)
            
            # Calculate revenue
            current_revenue = ProfitAndLossReport._calculate_revenue(start_date, end_date, business_id)
            previous_revenue = ProfitAndLossReport._calculate_revenue(prev_start, prev_end, business_id)
            
            # Calculate COGS
            current_cogs = ProfitAndLossReport._calculate_cogs(start_date, end_date, business_id)
            previous_cogs = ProfitAndLossReport._calculate_cogs(prev_start, prev_end, business_id)
            
            # Calculate gross profit
            current_gross = current_revenue - current_cogs
            previous_gross = previous_revenue - previous_cogs
            
            # Calculate operating expenses
            current_opex = ProfitAndLossReport._calculate_operating_expenses(start_date, end_date, business_id)
            previous_opex = ProfitAndLossReport._calculate_operating_expenses(prev_start, prev_end, business_id)
            
            # Calculate operating income
            current_operating = current_gross - current_opex
            previous_operating = previous_gross - previous_opex
            
            # Calculate taxes
            current_taxes = ProfitAndLossReport._calculate_taxes(start_date, end_date, business_id)
            previous_taxes = ProfitAndLossReport._calculate_taxes(prev_start, prev_end, business_id)
            
            # Calculate net income
            current_net = current_operating - current_taxes
            previous_net = previous_operating - previous_taxes
            
            # Build line items
            line_items = [
                ProfitAndLossReport._create_line_item('100', 'Revenue', 'Total Sales Revenue', current_revenue, previous_revenue),
                ProfitAndLossReport._create_line_item('200', 'Cost of Goods Sold', 'Direct costs of revenue', current_cogs, previous_cogs),
                ProfitAndLossReport._create_line_item('300', 'Gross Profit', 'Revenue minus COGS', current_gross, previous_gross),
                ProfitAndLossReport._create_line_item('400', 'Operating Expenses', 'Salaries, rent, utilities, etc.', current_opex, previous_opex),
                ProfitAndLossReport._create_line_item('500', 'Operating Income (EBIT)', 'Gross profit minus opex', current_operating, previous_operating),
                ProfitAndLossReport._create_line_item('600', 'Taxes', 'Income tax and levies', current_taxes, previous_taxes),
                ProfitAndLossReport._create_line_item('700', 'Net Income', 'Bottom line profit', current_net, previous_net),
            ]
            
            df = pl.DataFrame(line_items)
            
            # Calculate ratios and metrics
            metrics = {
                'gross_margin_current': (current_gross / current_revenue * 100) if current_revenue != 0 else 0,
                'gross_margin_previous': (previous_gross / previous_revenue * 100) if previous_revenue != 0 else 0,
                'operating_margin_current': (current_operating / current_revenue * 100) if current_revenue != 0 else 0,
                'operating_margin_previous': (previous_operating / previous_revenue * 100) if previous_revenue != 0 else 0,
                'net_margin_current': (current_net / current_revenue * 100) if current_revenue != 0 else 0,
                'net_margin_previous': (previous_net / previous_revenue * 100) if previous_revenue != 0 else 0,
            }
            
            return {
                'report_type': 'P&L Statement',
                'data': df.to_dicts() if not df.is_empty() else [],
                'columns': ProfitAndLossReport.COLUMNS,
                'title': f'Profit & Loss Statement - {start_date.strftime("%b %d, %Y")} to {end_date.strftime("%b %d, %Y")}',
                'period': {'start': start_date.isoformat(), 'end': end_date.isoformat()},
                'totals': {
                    'current_revenue': current_revenue,
                    'previous_revenue': previous_revenue,
                    'current_net_income': current_net,
                    'previous_net_income': previous_net,
                },
                'metrics': metrics,
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building P&L report: {str(e)}", exc_info=True)
            return {
                'report_type': 'P&L Statement',
                'error': str(e),
                'data': [],
                'columns': ProfitAndLossReport.COLUMNS,
            }
    
    @staticmethod
    def _create_line_item(code: str, line_item: str, description: str, current: Decimal, previous: Decimal) -> Dict[str, Any]:
        """Create a formatted P&L line item with variance."""
        current = float(current or 0)
        previous = float(previous or 0)
        variance = current - previous
        variance_pct = ((variance / previous * 100) if previous != 0 else 0)
        
        return {
            'line_item': f"{code} - {line_item}",
            'description': description,
            'current_period': current,
            'previous_period': previous,
            'variance_amount': variance,
            'variance_percent': round(variance_pct, 2),
        }
    
    @staticmethod
    def _calculate_revenue(start_date: date, end_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate total revenue from invoices and payments."""
        qs = BillingDocument.objects.filter(
            document_type='INVOICE',
            issue_date__gte=start_date,
            issue_date__lte=end_date,
            status__in=['completed', 'paid']
        )
        if business_id:
            qs = qs.filter(business_id=business_id)
        
        return qs.aggregate(total=Sum('total'))['total'] or Decimal('0')
    
    @staticmethod
    def _calculate_cogs(start_date: date, end_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate cost of goods sold from expenses marked as COGS."""
        qs = Expense.objects.filter(
            date_added__gte=start_date,
            date_added__lte=end_date,
            category__name__icontains='cogs'
        )
        if business_id:
            qs = qs.filter(branch__business_id=business_id)
        
        return qs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    
    @staticmethod
    def _calculate_operating_expenses(start_date: date, end_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate operating expenses (salaries, rent, utilities, etc.)."""
        exclude_categories = ['COGS', 'Non-Operating']
        qs = Expense.objects.filter(
            date_added__gte=start_date,
            date_added__lte=end_date,
            is_refund=False
        ).exclude(
            category__name__icontains='cogs'
        ).exclude(
            category__name__icontains='non-operating'
        )
        
        if business_id:
            qs = qs.filter(branch__business_id=business_id)
        
        return qs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    
    @staticmethod
    def _calculate_taxes(start_date: date, end_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate total taxes paid."""
        qs = Tax.objects.filter(
            tax_date__gte=start_date,
            tax_date__lte=end_date,
            status__in=['filed', 'paid']
        )
        if business_id:
            qs = qs.filter(business_id=business_id)
        
        return qs.aggregate(total=Sum('amount_due'))['total'] or Decimal('0')


class BalanceSheetReport:
    """
    Balance Sheet / Statement of Financial Position Report.
    
    Structure:
    ASSETS:
    - Current Assets (Cash, Receivables, Inventory)
    - Non-Current Assets (Fixed Assets, Investments)
    - Total Assets
    
    LIABILITIES:
    - Current Liabilities (Payables, Short-term debt)
    - Non-Current Liabilities (Long-term debt)
    - Total Liabilities
    
    EQUITY:
    - Paid-in Capital
    - Retained Earnings
    - Total Equity
    """
    
    REPORT_TYPE = 'Balance Sheet'
    
    COLUMNS = [
        {'field': 'line_item', 'header': 'Line Item'},
        {'field': 'description', 'header': 'Description'},
        {'field': 'current_date', 'header': f'Balance (KShs)'},
        {'field': 'previous_date', 'header': 'Comparison (KShs)'},
        {'field': 'change_amount', 'header': 'Change (KShs)'},
        {'field': 'change_percent', 'header': 'Change %'},
    ]
    
    @staticmethod
    def build(as_of_date: date, business_id: Optional[int] = None, previous_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Build Balance Sheet as of specific date.
        
        Args:
            as_of_date: Date for balance sheet
            business_id: Optional business filter
            previous_date: Optional comparison date (default: one year prior)
            
        Returns:
            Dict with balance sheet data, structure, and analysis
        """
        try:
            if not previous_date:
                previous_date = as_of_date - timedelta(days=365)
            
            # Calculate assets
            current_assets = BalanceSheetReport._calculate_current_assets(as_of_date, business_id)
            previous_assets = BalanceSheetReport._calculate_current_assets(previous_date, business_id)
            
            current_fixed_assets = BalanceSheetReport._calculate_fixed_assets(as_of_date, business_id)
            previous_fixed_assets = BalanceSheetReport._calculate_fixed_assets(previous_date, business_id)
            
            current_total_assets = current_assets + current_fixed_assets
            previous_total_assets = previous_assets + previous_fixed_assets
            
            # Calculate liabilities
            current_current_liab = BalanceSheetReport._calculate_current_liabilities(as_of_date, business_id)
            previous_current_liab = BalanceSheetReport._calculate_current_liabilities(previous_date, business_id)
            
            current_long_liab = BalanceSheetReport._calculate_long_term_liabilities(as_of_date, business_id)
            previous_long_liab = BalanceSheetReport._calculate_long_term_liabilities(previous_date, business_id)
            
            current_total_liab = current_current_liab + current_long_liab
            previous_total_liab = previous_current_liab + previous_long_liab
            
            # Calculate equity
            current_equity = current_total_assets - current_total_liab
            previous_equity = previous_total_assets - previous_total_liab
            
            # Build line items
            line_items = [
                # ASSETS
                BalanceSheetReport._create_line_item('100', 'Current Assets', 'Cash, receivables, inventory', current_assets, previous_assets),
                BalanceSheetReport._create_line_item('200', 'Fixed Assets', 'Property, equipment, vehicles', current_fixed_assets, previous_fixed_assets),
                BalanceSheetReport._create_line_item('300', 'TOTAL ASSETS', 'All assets', current_total_assets, previous_total_assets),
                # LIABILITIES
                BalanceSheetReport._create_line_item('400', 'Current Liabilities', 'Payables, short-term debt', current_current_liab, previous_current_liab),
                BalanceSheetReport._create_line_item('500', 'Long-term Liabilities', 'Long-term debt, deferred taxes', current_long_liab, previous_long_liab),
                BalanceSheetReport._create_line_item('600', 'TOTAL LIABILITIES', 'All liabilities', current_total_liab, previous_total_liab),
                # EQUITY
                BalanceSheetReport._create_line_item('700', 'Shareholders Equity', 'Paid-in capital + retained earnings', current_equity, previous_equity),
                BalanceSheetReport._create_line_item('800', 'TOTAL LIABILITIES + EQUITY', 'Liabilities and equity', current_total_liab + current_equity, previous_total_liab + previous_equity),
            ]
            
            df = pl.DataFrame(line_items)
            
            # Verify balance sheet equation
            assets_equal_liab_equity = abs((current_total_assets - (current_total_liab + current_equity)) < 0.01)
            
            return {
                'report_type': 'Balance Sheet',
                'data': df.to_dicts() if not df.is_empty() else [],
                'columns': BalanceSheetReport.COLUMNS,
                'title': f'Balance Sheet - As of {as_of_date.strftime("%b %d, %Y")}',
                'as_of_date': as_of_date.isoformat(),
                'comparison_date': previous_date.isoformat(),
                'totals': {
                    'total_assets': current_total_assets,
                    'total_liabilities': current_total_liab,
                    'total_equity': current_equity,
                },
                'validation': {
                    'equation_balanced': assets_equal_liab_equity,
                    'assets_equal_liab_equity': current_total_assets == (current_total_liab + current_equity),
                },
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building Balance Sheet: {str(e)}", exc_info=True)
            return {
                'report_type': 'Balance Sheet',
                'error': str(e),
                'data': [],
                'columns': BalanceSheetReport.COLUMNS,
            }
    
    @staticmethod
    def _create_line_item(code: str, line_item: str, description: str, current: Decimal, previous: Decimal) -> Dict[str, Any]:
        """Create formatted balance sheet line item with change analysis."""
        current = float(current or 0)
        previous = float(previous or 0)
        change = current - previous
        change_pct = ((change / previous * 100) if previous != 0 else 0)
        
        return {
            'line_item': f"{code} - {line_item}",
            'description': description,
            'current_date': current,
            'previous_date': previous,
            'change_amount': change,
            'change_percent': round(change_pct, 2),
        }
    
    @staticmethod
    def _calculate_current_assets(as_of_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate current assets (cash + short-term receivables)."""
        qs = PaymentAccounts.objects.filter(
            account_type__in=['cash', 'bank', 'receivable'],
            is_active=True
        )
        if business_id:
            qs = qs.filter(business_id=business_id)
        
        return qs.aggregate(total=Sum('balance'))['total'] or Decimal('0')
    
    @staticmethod
    def _calculate_fixed_assets(as_of_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate fixed assets (property, equipment, vehicles)."""
        qs = PaymentAccounts.objects.filter(
            account_type__in=['asset', 'fixed_asset'],
            is_active=True
        )
        if business_id:
            qs = qs.filter(business_id=business_id)
        
        return qs.aggregate(total=Sum('balance'))['total'] or Decimal('0')
    
    @staticmethod
    def _calculate_current_liabilities(as_of_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate current liabilities (payables, short-term debt)."""
        qs = PaymentAccounts.objects.filter(
            account_type__in=['payable', 'current_liability'],
            is_active=True
        )
        if business_id:
            qs = qs.filter(business_id=business_id)
        
        balance = qs.aggregate(total=Sum('balance'))['total'] or Decimal('0')
        return abs(balance) if balance < 0 else balance
    
    @staticmethod
    def _calculate_long_term_liabilities(as_of_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate long-term liabilities and non-current liabilities."""
        qs = PaymentAccounts.objects.filter(
            account_type__in=['loan', 'long_term_liability'],
            is_active=True
        )
        if business_id:
            qs = qs.filter(business_id=business_id)
        
        balance = qs.aggregate(total=Sum('balance'))['total'] or Decimal('0')
        return abs(balance) if balance < 0 else balance


class CashFlowReport:
    """
    Cash Flow Statement Report (Direct Method).
    
    Structure:
    - Operating Activities (Net income, adjustments)
    - Investing Activities (Asset purchases, sales)
    - Financing Activities (Debt, equity changes)
    - Net Change in Cash
    """
    
    REPORT_TYPE = 'Cash Flow Statement'
    
    COLUMNS = [
        {'field': 'line_item', 'header': 'Line Item'},
        {'field': 'description', 'header': 'Description'},
        {'field': 'amount', 'header': 'Amount (KShs)'},
    ]
    
    @staticmethod
    def build(start_date: date, end_date: date, business_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Build Cash Flow statement for period.
        
        Args:
            start_date: Period start date
            end_date: Period end date
            business_id: Optional business filter
            
        Returns:
            Dict with cash flow data and analysis
        """
        try:
            # Operating activities
            operating_cash_in = CashFlowReport._calculate_operating_inflows(start_date, end_date, business_id)
            operating_cash_out = CashFlowReport._calculate_operating_outflows(start_date, end_date, business_id)
            operating_net = operating_cash_in - operating_cash_out
            
            # Investing activities
            investing_cash_in = CashFlowReport._calculate_investing_inflows(start_date, end_date, business_id)
            investing_cash_out = CashFlowReport._calculate_investing_outflows(start_date, end_date, business_id)
            investing_net = investing_cash_in - investing_cash_out
            
            # Financing activities
            financing_cash_in = CashFlowReport._calculate_financing_inflows(start_date, end_date, business_id)
            financing_cash_out = CashFlowReport._calculate_financing_outflows(start_date, end_date, business_id)
            financing_net = financing_cash_in - financing_cash_out
            
            # Net change in cash
            net_cash_change = operating_net + investing_net + financing_net
            
            # Build line items
            line_items = [
                # Operating
                CashFlowReport._create_line_item('100', 'Operating Activities', 'Cash from operations', ''),
                CashFlowReport._create_line_item('110', 'Cash Inflows', 'Invoice collections, payments received', operating_cash_in),
                CashFlowReport._create_line_item('120', 'Cash Outflows', 'Expense payments, payroll', -operating_cash_out),
                CashFlowReport._create_line_item('130', 'Net Operating Cash Flow', 'Operating net cash', operating_net),
                # Investing
                CashFlowReport._create_line_item('200', 'Investing Activities', 'Asset purchases and sales', ''),
                CashFlowReport._create_line_item('210', 'Cash Inflows', 'Asset sales, investment returns', investing_cash_in),
                CashFlowReport._create_line_item('220', 'Cash Outflows', 'Asset purchases', -investing_cash_out),
                CashFlowReport._create_line_item('230', 'Net Investing Cash Flow', 'Investing net cash', investing_net),
                # Financing
                CashFlowReport._create_line_item('300', 'Financing Activities', 'Debt and equity changes', ''),
                CashFlowReport._create_line_item('310', 'Cash Inflows', 'Loans, equity investment', financing_cash_in),
                CashFlowReport._create_line_item('320', 'Cash Outflows', 'Debt repayment, dividends', -financing_cash_out),
                CashFlowReport._create_line_item('330', 'Net Financing Cash Flow', 'Financing net cash', financing_net),
                # Total
                CashFlowReport._create_line_item('400', 'Net Change in Cash', 'Total cash movement', net_cash_change),
            ]
            
            df = pl.DataFrame([item for item in line_items if item.get('amount') != ''])
            
            return {
                'report_type': 'Cash Flow Statement',
                'data': df.to_dicts() if not df.is_empty() else [],
                'columns': CashFlowReport.COLUMNS,
                'title': f'Cash Flow Statement - {start_date.strftime("%b %d, %Y")} to {end_date.strftime("%b %d, %Y")}',
                'period': {'start': start_date.isoformat(), 'end': end_date.isoformat()},
                'totals': {
                    'operating_net': operating_net,
                    'investing_net': investing_net,
                    'financing_net': financing_net,
                    'net_cash_change': net_cash_change,
                },
                'row_count': len(df),
                'generated_at': timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error building Cash Flow report: {str(e)}", exc_info=True)
            return {
                'report_type': 'Cash Flow Statement',
                'error': str(e),
                'data': [],
                'columns': CashFlowReport.COLUMNS,
            }
    
    @staticmethod
    def _create_line_item(code: str, line_item: str, description: str, amount=None) -> Dict[str, Any]:
        """Create cash flow line item."""
        return {
            'line_item': f"{code} - {line_item}",
            'description': description,
            'amount': float(amount) if amount != '' else '',
        }
    
    @staticmethod
    def _calculate_operating_inflows(start_date: date, end_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate cash inflows from operations (invoice collections)."""
        qs = Payment.objects.filter(
            payment_date__gte=start_date,
            payment_date__lte=end_date,
            status__in=['completed', 'reconciled']
        )
        if business_id:
            qs = qs.filter(business_id=business_id)
        
        return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    @staticmethod
    def _calculate_operating_outflows(start_date: date, end_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate cash outflows from operations (expenses, payroll)."""
        qs = Expense.objects.filter(
            date_added__gte=start_date,
            date_added__lte=end_date
        )
        if business_id:
            qs = qs.filter(branch__business_id=business_id)
        
        return qs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    
    @staticmethod
    def _calculate_investing_inflows(start_date: date, end_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate cash inflows from investing activities (asset sales)."""
        qs = Transaction.objects.filter(
            transaction_date__gte=start_date,
            transaction_date__lte=end_date,
            transaction_type='refund'
        )
        if business_id:
            qs = qs.filter(account__business_id=business_id)
        
        return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    @staticmethod
    def _calculate_investing_outflows(start_date: date, end_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate cash outflows from investing (asset purchases)."""
        # Placeholder for asset purchase tracking
        # Would typically query fixed asset purchase records
        return Decimal('0')
    
    @staticmethod
    def _calculate_financing_inflows(start_date: date, end_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate cash inflows from financing (loans, equity)."""
        qs = Transaction.objects.filter(
            transaction_date__gte=start_date,
            transaction_date__lte=end_date,
            transaction_type__in=['payment', 'transfer']
        )
        if business_id:
            qs = qs.filter(account__business_id=business_id)
        
        return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    @staticmethod
    def _calculate_financing_outflows(start_date: date, end_date: date, business_id: Optional[int]) -> Decimal:
        """Calculate cash outflows from financing (debt repayment)."""
        qs = Transaction.objects.filter(
            transaction_date__gte=start_date,
            transaction_date__lte=end_date,
            transaction_type='expense'
        )
        if business_id:
            qs = qs.filter(account__business_id=business_id)
        
        return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')


class FinanceReportFormatter:
    """Main Finance Report Formatter - Orchestrates all financial statements."""
    
    @staticmethod
    def generate_p_and_l(start_date: date, end_date: date, business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate Profit & Loss statement."""
        return ProfitAndLossReport.build(start_date, end_date, business_id)
    
    @staticmethod
    def generate_balance_sheet(as_of_date: date, business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate Balance Sheet statement."""
        return BalanceSheetReport.build(as_of_date, business_id)
    
    @staticmethod
    def generate_cash_flow(start_date: date, end_date: date, business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate Cash Flow statement."""
        return CashFlowReport.build(start_date, end_date, business_id)
    
    @staticmethod
    def generate_all_statements(start_date: date, end_date: date, business_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate all financial statements for a period."""
        return {
            'p_and_l': ProfitAndLossReport.build(start_date, end_date, business_id),
            'balance_sheet': BalanceSheetReport.build(end_date, business_id),
            'cash_flow': CashFlowReport.build(start_date, end_date, business_id),
            'generated_at': timezone.now().isoformat(),
        }
