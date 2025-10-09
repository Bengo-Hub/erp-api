"""
Finance module central API views for integrating data across all finance submodules.
"""
from datetime import datetime, timedelta
from django.db.models import Sum, Count, Q
from django.utils import timezone
from rest_framework import viewsets, status, views
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .accounts.models import PaymentAccounts, Transaction
from .expenses.models import Expense
from .taxes.models import Tax, TaxPeriod
from .payment.models import BillingDocument, Payment
from business.models import Bussiness, BusinessLocation, Branch
from finance.payment.models import BillingDocument as FinanceBillingDocument, Payment as FinancePayment
from finance.expenses.models import Expense as FinanceExpense
from finance.accounts.models import PaymentAccounts as FinancePaymentAccounts
from finance.payment.models import PaymentTransaction
from .analytics.finance_analytics import FinanceAnalyticsService
import logging

logger = logging.getLogger('ditapi_logger')

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def finance_analytics(request):
    """
    Get finance analytics data.
    """
    try:
        period = request.query_params.get('period', 'month')
        business_id = request.query_params.get('business_id')
        
        analytics_service = FinanceAnalyticsService()
        data = analytics_service.get_finance_dashboard_data(
            business_id=business_id,
            period=period
        )
        
        return Response({
            'success': True,
            'data': data,
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error fetching finance analytics: {str(e)}',
            'timestamp': timezone.now().isoformat()
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def get_financial_summary(start_date, end_date):
    # Calculate totals and outstanding amounts for the given date range
    total_invoices = BillingDocument.objects.filter(
        document_type=BillingDocument.INVOICE,
        issue_date__gte=start_date,
        issue_date__lte=end_date
    ).aggregate(total=Sum('total'))['total'] or 0

    total_payments = Payment.objects.filter(
        payment_date__gte=start_date,
        payment_date__lte=end_date
    ).aggregate(total=Sum('amount'))['total'] or 0

    total_expenses = Expense.objects.filter(
        date_added__gte=start_date,
        date_added__lte=end_date
    ).aggregate(total=Sum('total_amount'))['total'] or 0

    outstanding_invoices = BillingDocument.objects.filter(
        document_type=BillingDocument.INVOICE,
        issue_date__gte=start_date,
        issue_date__lte=end_date,
        balance_due__gt=0
    ).aggregate(total=Sum('balance_due'))['total'] or 0

    return {
        'total_invoices': total_invoices,
        'total_payments': total_payments,
        'total_expenses': total_expenses,
        'outstanding_invoices': outstanding_invoices
    }

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def finance_dashboard(request):
    """
    Get a unified financial dashboard with data from all finance modules.
    
    Includes:
    - Recent invoices
    - Recent payments
    - Recent expenses
    - Financial summary (totals, outstanding amounts)
    - Account balances
    """
    # Get query parameters for date filtering
    # Support both 'period' semantic values and 'days' for backward-compatibility
    period = request.query_params.get('period')
    days_param = request.query_params.get('days')
    period_to_days = {
        'week': 7,
        'month': 30,
        'quarter': 90,
        'year': 365,
    }
    if days_param:
        try:
            days = int(days_param)
            if days < 1:
                days = 30
        except (ValueError, TypeError):
            days = 30
    elif period in period_to_days:
        days = period_to_days[period]
    else:
        days = 30
        
    start_date = timezone.now().date() - timedelta(days=days)
    end_date = timezone.now().date()
    
    # Get financial summary
    summary = get_financial_summary(start_date, end_date)
    
    # Recent invoices
    recent_invoices = BillingDocument.objects.filter(
        document_type=BillingDocument.INVOICE
    ).order_by('-issue_date')[:5]
    
    # Recent payments
    recent_payments = Payment.objects.all().order_by('-payment_date')[:5]
    
    # Recent expenses
    recent_expenses = Expense.objects.all().order_by('-date_added')[:5]
    
    # Account balances
    accounts = PaymentAccounts.objects.all()
    account_balances = []
    for account in accounts:
        # Get credit transactions
        credits = Transaction.objects.filter(
            account=account, 
            transaction_type__in=['income', 'refund']
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # Get debit transactions
        debits = Transaction.objects.filter(
            account=account, 
            transaction_type__in=['expense', 'payment', 'transfer']
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # Calculate balance
        balance = getattr(account, 'opening_balance', 0) + credits - debits
        
        account_balances.append({
            'id': getattr(account, 'pk', None),
            'name': getattr(account, 'name', ''),
            'account_number': getattr(account, 'account_number', ''),
            'balance': balance
        })
    
    # Build trends data (simple daily aggregation over the window)
    try:
        revenue_qs = BillingDocument.objects.filter(
            document_type=BillingDocument.INVOICE,
            issue_date__gte=start_date,
            issue_date__lte=end_date
        ).values('issue_date').annotate(amount=Sum('total')).order_by('issue_date')
        revenue_trends = [
            {
                'period': item['issue_date'].isoformat() if hasattr(item['issue_date'], 'isoformat') else str(item['issue_date']),
                'amount': float(item['amount'] or 0)
            }
            for item in revenue_qs
        ]
    except Exception as e:
        logger.error(f"Error getting revenue trends: {e}")
        revenue_trends = []

    try:
        payments_qs = Payment.objects.filter(
            payment_date__gte=start_date,
            payment_date__lte=end_date
        ).values('payment_date').annotate(amount=Sum('amount')).order_by('payment_date')
        expenses_qs = Expense.objects.filter(
            date_added__gte=start_date,
            date_added__lte=end_date
        ).values('date_added').annotate(amount=Sum('total_amount')).order_by('date_added')

        # Merge by date for cash flow (payments - expenses)
        cash_map = {}
        for p in payments_qs:
            key = p['payment_date'].date().isoformat() if hasattr(p['payment_date'], 'date') else str(p['payment_date'])
            cash_map[key] = cash_map.get(key, 0) + float(p['amount'] or 0)
        for e in expenses_qs:
            key = e['date_added'].date().isoformat() if hasattr(e['date_added'], 'date') else str(e['date_added'])
            cash_map[key] = cash_map.get(key, 0) - float(e['amount'] or 0)
        cash_flow_data = [
            {'period': k, 'amount': v}
            for k, v in sorted(cash_map.items())
        ]
    except Exception as e:
        logger.error(f"Error getting cash flow data: {e}")
        cash_flow_data = []

    # Expense breakdown by category (top categories)
    try:
        from .expenses.models import ExpenseCategory
        categories = ExpenseCategory.objects.all()
        expense_breakdown = []
        for category in categories:
            amt = Expense.objects.filter(
                category=category,
                date_added__gte=start_date,
                date_added__lte=end_date
            ).aggregate(total=Sum('total_amount'))['total'] or 0
            if amt:
                expense_breakdown.append({'category': category.name, 'amount': float(amt)})
    except Exception as e:
        logger.error(f"Error getting expense breakdown: {e}")
        expense_breakdown = []

    total_revenue = float(summary.get('total_invoices', 0) or 0)
    total_expenses = float(summary.get('total_expenses', 0) or 0)
    total_payments = float(summary.get('total_payments', 0) or 0)
    net_profit = total_revenue - total_expenses
    cash_flow = total_payments - total_expenses

    # Format the response data with fallbacks expected by UI
    response_data = {
        'summary': summary,
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'cash_flow': cash_flow,
        'outstanding_invoices': float(summary.get('outstanding_invoices', 0) or 0),
        'overdue_payments': 0,
        'tax_summary': {},
        'revenue_trends': revenue_trends,
        'expense_breakdown': expense_breakdown,
        'cash_flow_data': cash_flow_data,
        'recent_invoices': [{
            'id': getattr(invoice, 'pk', None),
            'document_number': getattr(invoice, 'document_number', None),
            'customer_name': getattr(getattr(invoice, 'customer', None), 'name', None),
            'issue_date': getattr(invoice, 'issue_date', None),
            'due_date': getattr(invoice, 'due_date', None),
            'total': getattr(invoice, 'total', 0),
            'balance_due': getattr(invoice, 'balance_due', 0),
            'status': getattr(invoice, 'status', ''),
            'status_display': getattr(invoice, 'status', '')
        } for invoice in recent_invoices],
        'recent_payments': [{
            'id': getattr(payment, 'pk', None),
            'document_number': getattr(getattr(payment, 'document', None), 'document_number', None),
            'customer_name': getattr(getattr(getattr(payment, 'document', None), 'customer', None), 'name', None),
            'payment_date': getattr(payment, 'payment_date', None),
            'amount': getattr(payment, 'amount', 0),
            'payment_method': getattr(payment, 'payment_method', '')
        } for payment in recent_payments],
        'recent_expenses': [{
            'id': getattr(expense, 'pk', None),
            'reference_no': getattr(expense, 'reference_no', ''),
            'date_added': getattr(expense, 'date_added', None),
            'category': getattr(getattr(expense, 'category', None), 'name', None),
            'total_amount': getattr(expense, 'total_amount', 0)
        } for expense in recent_expenses],
        'account_balances': account_balances
    }
    
    return Response(response_data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tax_summary(request):
    """
    Get a summary of tax information from all finance modules.
    
    Includes:
    - Tax collected by tax rate
    - Current tax period status
    - Outstanding tax liabilities
    """
    # Get query parameters for date filtering
    year = request.query_params.get('year', datetime.now().year)
    try:
        year = int(year)
    except (ValueError, TypeError):
        year = datetime.now().year
    
    # Get tax periods for the year
    tax_periods = TaxPeriod.objects.filter(
        start_date__year=year
    ).order_by('start_date')
    
    # Get taxes collected by tax rate for this year
    taxes_collected = []
    taxes = Tax.objects.filter(is_active=True)
    
    for tax in taxes:
        # We'd need to sum up tax amounts from invoices with this tax rate
        # This is a simplified example, real implementation would be more complex
        # and would need to consider tax groups, line items with different taxes, etc.
        collected = BillingDocument.objects.filter(
            document_type=BillingDocument.INVOICE,
            issue_date__year=year,
            tax_amount__gt=0
        ).aggregate(total=Sum('tax_amount'))['total'] or 0
        
        taxes_collected.append({
            'id': getattr(tax, 'pk', None),
            'name': tax.name,
            'rate': tax.rate,
            'collected': collected
        })
    
    return Response({
        'year': year,
        'tax_periods': [{
            'id': getattr(period, 'pk', None),
            'name': period.name,
            'start_date': period.start_date,
            'end_date': period.end_date,
            'due_date': period.due_date,
            'status': period.status,
            'total_collected': period.total_collected,
            'total_paid': period.total_paid
        } for period in tax_periods],
        'taxes_collected': taxes_collected
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def finance_branches(request):
    """
    Get business branches for finance reports.
    """
    try:
        business_name = request.query_params.get('business_name')
        
        if business_name:
            # Get branches for specific business
            branches = Branch.objects.filter(
                business__name__icontains=business_name,
                is_active=True
            ).select_related('business', 'location')
        else:
            # Get all active branches
            branches = Branch.objects.filter(is_active=True).select_related('business', 'location')
        
        branch_data = []
        for branch in branches:
            branch_data.append({
                'id': branch.id,
                'branch_code': branch.branch_code,
                'branch_name': branch.name,
                'business_name': branch.business.name,
                'city': branch.location.city,
                'county': branch.location.county,
                'constituency': branch.location.constituency,
                'ward': branch.location.ward,
                'street_name': branch.location.street_name,
                'building_name': branch.location.building_name,
                'state': str(branch.location.state) if branch.location.state else None,
                'country': str(branch.location.country) if branch.location.country else None,
                'contact_number': branch.contact_number,
                'email': branch.email,
                'is_main_branch': branch.is_main_branch,
                'is_active': branch.is_active
            })
        
        return Response({
            'success': True,
            'results': branch_data,
            'count': len(branch_data)
        })
    except Exception as e:
        logger.error(f"Error fetching branches: {e}")
        return Response({
            'success': False,
            'message': f'Error fetching branches: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def finance_reports(request):
    """
    Generate financial reports from all finance modules.
    
    Supported report types:
    - profit_loss: Profit and Loss statement
    - balance_sheet: Balance Sheet
    - cash_flow: Cash Flow statement
    - tax: Tax report
    - expense: Expense report
    """
    report_type = request.query_params.get('type', 'profit_loss')
    start_date = request.query_params.get('start_date', (timezone.now().date() - timedelta(days=30)).isoformat())
    end_date = request.query_params.get('end_date', timezone.now().date().isoformat())
    
    # Convert string dates to date objects
    try:
        start_date = datetime.fromisoformat(start_date).date()
    except ValueError:
        start_date = timezone.now().date() - timedelta(days=30)
        
    try:
        end_date = datetime.fromisoformat(end_date).date()
    except ValueError:
        end_date = timezone.now().date()
    
    # Generate the requested report
    if report_type == 'profit_loss':
        # Revenue
        revenue = BillingDocument.objects.filter(
            document_type=BillingDocument.INVOICE,
            issue_date__gte=start_date,
            issue_date__lte=end_date
        ).aggregate(total=Sum('total'))['total'] or 0
        
        # Cost of goods sold (simplified)
        cogs = 0  # Would need inventory data to calculate
        
        # Gross profit
        gross_profit = revenue - cogs
        
        # Expenses
        expenses = Expense.objects.filter(
            date_added__gte=start_date,
            date_added__lte=end_date
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        # Net profit
        net_profit = gross_profit - expenses
        
        return Response({
            'report_type': 'Profit and Loss',
            'start_date': start_date,
            'end_date': end_date,
            'revenue': revenue,
            'cost_of_goods_sold': cogs,
            'gross_profit': gross_profit,
            'expenses': expenses,
            'net_profit': net_profit
        })
        
    elif report_type == 'tax':
        # Tax collected
        tax_collected = BillingDocument.objects.filter(
            document_type=BillingDocument.INVOICE,
            issue_date__gte=start_date,
            issue_date__lte=end_date
        ).aggregate(total=Sum('tax_amount'))['total'] or 0
        
        # Tax paid
        tax_paid = TaxPeriod.objects.filter(
            start_date__gte=start_date,
            end_date__lte=end_date
        ).aggregate(total=Sum('total_paid'))['total'] or 0
        
        # Tax due
        tax_due = tax_collected - tax_paid
        
        return Response({
            'report_type': 'Tax Report',
            'start_date': start_date,
            'end_date': end_date,
            'tax_collected': tax_collected,
            'tax_paid': tax_paid,
            'tax_due': tax_due
        })
        
    elif report_type == 'expense':
        # Get expenses by category
        expenses_by_category = []
        from .expenses.models import ExpenseCategory
        
        categories = ExpenseCategory.objects.all()
        for category in categories:
            amount = Expense.objects.filter(
                category=category,
                date_added__gte=start_date,
                date_added__lte=end_date
            ).aggregate(total=Sum('total_amount'))['total'] or 0
            
            if amount > 0:
                expenses_by_category.append({
                    'category': category.name,
                    'amount': amount
                })
        
        # Total expenses
        total_expenses = Expense.objects.filter(
            date_added__gte=start_date,
            date_added__lte=end_date
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        return Response({
            'report_type': 'Expense Report',
            'start_date': start_date,
            'end_date': end_date,
            'total_expenses': total_expenses,
            'expenses_by_category': expenses_by_category
        })
    
    elif report_type == 'balance_sheet':
        # Get account balances
        account_balances = []
        try:
            accounts = PaymentAccounts.objects.all()
            for account in accounts:
                # Calculate current balance
                balance = account.opening_balance or 0
                account_balances.append({
                    'account_name': account.name,
                    'account_type': account.account_type,
                    'balance': balance,
                    'category': 'Assets' if balance >= 0 else 'Liability'
                })
        except Exception as e:
            logger.error(f"Error getting account balances: {e}")
            account_balances = []
        
        # Calculate totals
        total_assets = sum([acc['balance'] for acc in account_balances if acc['balance'] >= 0])
        total_liabilities = abs(sum([acc['balance'] for acc in account_balances if acc['balance'] < 0]))
        
        return Response({
            'report_type': 'Balance Sheet',
            'start_date': start_date,
            'end_date': end_date,
            'account_balances': account_balances,
            'total_assets': total_assets,
            'total_liabilities': total_liabilities,
            'equity': total_assets - total_liabilities
        })
        
    elif report_type == 'trial_balance':
        # Get trial balance data
        trial_balance_data = []
        try:
            accounts = PaymentAccounts.objects.all()
            for account in accounts:
                balance = account.opening_balance or 0
                trial_balance_data.append({
                    'name': account.name,
                    'category': 'Credit' if balance < 0 else 'Debit',
                    'amount': abs(balance)
                })
        except Exception as e:
            logger.error(f"Error getting trial balance: {e}")
            trial_balance_data = []
        
        return Response({
            'report_type': 'Trial Balance',
            'start_date': start_date,
            'end_date': end_date,
            'data': trial_balance_data
        })
        
    elif report_type == 'sales_overview':
        # Get sales overview data
        try:
            # Revenue
            revenue = BillingDocument.objects.filter(
                document_type=BillingDocument.INVOICE,
                issue_date__gte=start_date,
                issue_date__lte=end_date
            ).aggregate(total=Sum('total'))['total'] or 0
            
            # Cost of goods sold (simplified)
            cogs = 0  # Would need inventory data to calculate
            
            # Gross profit
            gross_profit = revenue - cogs
            
            # Expenses
            expenses = Expense.objects.filter(
                date_added__gte=start_date,
                date_added__lte=end_date
            ).aggregate(total=Sum('total_amount'))['total'] or 0
            
            # Net profit
            net_profit = gross_profit - expenses
            
            # Mock data for stock values (would need inventory integration)
            opening_stock_by_purchase_price = 0
            opening_stock_by_sale_price = 0
            closing_stock_by_purchase_price = 0
            closing_stock_by_sale_price = 0
            
            return Response({
                'report_type': 'Sales Overview',
                'start_date': start_date,
                'end_date': end_date,
                'opening_stock_by_purchase_price': opening_stock_by_purchase_price,
                'opening_stock_by_sale_price': opening_stock_by_sale_price,
                'total_purchase_exc_tax_discount': 0,
                'total_stock_adjustment': 0,
                'total_expense': expenses,
                'total_purchase_shipping_charge': 0,
                'purchase_additional_expenses': 0,
                'total_transfer_shipping_charge': 0,
                'total_sell_discount': 0,
                'total_customer_reward': 0,
                'total_sell_return': 0,
                'closing_stock_by_purchase_price': closing_stock_by_purchase_price,
                'closing_stock_by_sale_price': closing_stock_by_sale_price,
                'total_sales_exc_tax_discount': revenue,
                'total_sell_shipping_charge': 0,
                'sell_additional_expenses': 0,
                'total_stock_recovered': 0,
                'total_purchase_return': 0,
                'total_purchase_discount': 0,
                'gross_profit': gross_profit,
                'net_profit': net_profit
            })
        except Exception as e:
            logger.error(f"Error getting sales overview: {e}")
            return Response({
                'error': f'Error generating sales overview: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    # Unsupported report type
    return Response({
        'error': f'Unsupported report type: {report_type}',
        'supported_types': ['profit_loss', 'tax', 'expense', 'balance_sheet', 'trial_balance', 'sales_overview']
    }, status=status.HTTP_400_BAD_REQUEST)
