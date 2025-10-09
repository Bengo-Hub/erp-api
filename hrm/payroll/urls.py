from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register(r'payroll', ProcessPayrollViewSet, basename='payroll')
router.register(r'payroll-audits', PayrollAuditsViewSet, basename='payroll-audits')
router.register(r'advances', EmployeeAdvancesViewSet, basename='advances')
router.register(r'losses-damages', EmployeeLossDamagesViewSet, basename='loss-damages')
router.register(r'claims', ExpenseClaimViewSet, basename='claim')
router.register(r'claim-items', ClaimItemViewSet, basename='claim-item')
router.register(r'approvals', PayrollApprovalViewSet, basename='payroll_approval')

urlpatterns = [
    path('', include(router.urls)),
    path('email-payslips', EmailPayslipsView.as_view(), name='email-payslips'),
    path('analytics/', payroll_analytics, name='payroll-analytics'),
]
