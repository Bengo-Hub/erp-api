"""
Finance module URL configuration.
"""
from django.urls import path, include
from .services.analytics_views import finance_analytics, finance_dashboard, tax_summary
from .services.reports_views import (
    profit_and_loss_report,
    balance_sheet_report,
    cash_flow_report,
    financial_statements_suite
)

urlpatterns = [
    # Finance Analytics Endpoints
    path('analytics/', finance_analytics, name='finance-analytics'),
    path('dashboard/', finance_dashboard, name='finance-dashboard'),
    path('tax-summary/', tax_summary, name='finance-tax-summary'),
    
    # Financial Reports Endpoints
    path('reports/profit-loss/', profit_and_loss_report, name='finance-profit-loss'),
    path('reports/balance-sheet/', balance_sheet_report, name='finance-balance-sheet'),
    path('reports/cash-flow/', cash_flow_report, name='finance-cash-flow'),
    path('reports/statements-suite/', financial_statements_suite, name='finance-statements-suite'),
    
    # Include submodule URLs
    path('accounts/', include('finance.accounts.urls')),
    path('expenses/', include('finance.expenses.urls')),
    path('payment/', include('finance.payment.urls')),
    path('taxes/', include('finance.taxes.urls')),
    path('budgets/', include('finance.budgets.urls')),
    path('cashflow/', include('finance.cashflow.urls')),
    path('reconciliation/', include('finance.reconciliation.urls')),
    
    # NEW: Invoice and Quotation modules
    path('invoicing/', include('finance.invoicing.urls')),
    path('quotations/', include('finance.quotations.urls')),
]
