from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from .reports_views import (
    p9_tax_report, p10a_employer_return, statutory_deductions_report,
    bank_net_pay_report, muster_roll_report, withholding_tax_report,
    variance_report
)
router = DefaultRouter()
router.register(r'payroll', ProcessPayrollViewSet, basename='payroll')
router.register(r'payroll-audits', PayrollAuditsViewSet, basename='payroll-audits')
router.register(r'advances', EmployeeAdvancesViewSet, basename='advances')
router.register(r'losses-damages', EmployeeLossDamagesViewSet, basename='loss-damages')
router.register(r'claims', ExpenseClaimViewSet, basename='claim')
router.register(r'expense-claim-settings', ExpenseClaimSettingsViewSet, basename='expense-claim-settings')
router.register(r'expense-codes', ExpenseCodeViewSet, basename='expense-codes')
router.register(r'claim-items', ClaimItemViewSet, basename='claim-item')
router.register(r'approvals', PayrollApprovalViewSet, basename='payroll_approval')
router.register(r'custom-reports', CustomReportViewSet, basename='custom-report')


urlpatterns = [
    path('', include(router.urls)),
    path('email-payslips', EmailPayslipsView.as_view(), name='email-payslips'),
    path('analytics/', payroll_analytics, name='payroll-analytics'),
    
    # Report endpoints
    path('reports/p9/', p9_tax_report, name='p9-report'),
    path('reports/p10a/', p10a_employer_return, name='p10a-report'),
    path('reports/statutory-deductions/', statutory_deductions_report, name='statutory-deductions-report'),
    path('reports/bank-net-pay/', bank_net_pay_report, name='bank-net-pay-report'),
    path('reports/muster-roll/', muster_roll_report, name='muster-roll-report'),
    path('reports/withholding-tax/', withholding_tax_report, name='withholding-tax-report'),
    path('reports/variance/', variance_report, name='variance-report'),
]