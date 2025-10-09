from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register(r'scheduled-payslips', ScheduledPayslipViewSet, basename='scheduled-payslips')
router.register(r'payroll-components', PayrollComponentsViewSet, basename='payroll-components')
router.register(r'approvals', ApprovalViewSet, basename='approvals')
router.register(r'formulas', FormulaViewSet, basename='formulas')
router.register(r'components', PayrollComponentsViewSet, basename='components')

urlpatterns = [
    path('', include(router.urls)),
    path('formula-management/', FormulaManagementAPIView.as_view(), name='formula-management'),
]
