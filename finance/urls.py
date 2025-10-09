"""
Finance module URL configuration.
"""
from django.urls import path, include
from .api import finance_analytics, finance_dashboard, tax_summary, finance_reports, finance_branches

urlpatterns = [
    # Main finance endpoints
    path('analytics/', finance_analytics, name='finance-analytics'),
    path('dashboard/', finance_dashboard, name='finance-dashboard'),
    path('tax-summary/', tax_summary, name='finance-tax-summary'),
    path('reports/', finance_reports, name='finance-reports'),
    path('branches/', finance_branches, name='finance-branches'),
    
    # Include submodule URLs
    path('accounts/', include('finance.accounts.urls')),
    path('expenses/', include('finance.expenses.urls')),
    path('payment/', include('finance.payment.urls')),
    path('taxes/', include('finance.taxes.urls')),
    path('budgets/', include('finance.budgets.urls')),
    path('cashflow/', include('finance.cashflow.urls')),
    path('reconciliation/', include('finance.reconciliation.urls')),
]
