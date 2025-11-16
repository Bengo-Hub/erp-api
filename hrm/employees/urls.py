from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from .views import employee_analytics

router = DefaultRouter()
router.register(r'employees', EmployeeViewSet)
router.register(r'job-titles', JobTitleViewSet)
router.register(r'job-groups', JobGroupViewSet)
router.register(r'workers-unions', WorkersUnionViewSet)
# ESS Settings uses APIView instead of ViewSet to avoid employee filtering
router.register(r'salary-details', SalaryDetailsViewSet)
router.register(r'hr-details', HRDetailsViewSet)
router.register(r'contracts', ContractViewSet)
router.register(r'deductions', EmployeeDeductionsViewSet)
router.register(r'benefits', EmployeeBenefitsViewSet)
router.register(r'earnings', EmployeeEarningsViewSet)
#router.register(r'basic-pay', EmployeeBasicPayViewSet)
router.register(r'loans', EmployeeLoansViewSet)  # Use an appropriate URL prefix
router.register(r'contact-details', ContactDetailsViewSet)
router.register(r'next-of-kin', NextOfKinViewSet)
router.register(r'employee-payroll-data', EmployeePayrollDataViewSet, basename='employee-payroll-data')
router.register(r'bank-accounts', EmployeeBankAccountViewSet)

urlpatterns = [
    path('', include(router.urls)),  # Remove the extra 'employees/' prefix
    path('upload-employee-data/', UploadEmployData.as_view(), name='upload-employee-data'),
    path('employee-status/', EmployeeStatusAPIView.as_view(), name='employee-status'),  # Remove extra 'employees/' prefix
    path('analytics/', employee_analytics, name='employee-analytics'),
    # ESS Settings - using APIView to bypass employee filtering
    path('ess-settings/', ESSSettingsViewSet.as_view(), name='ess-settings-list'),
    path('ess-settings/<int:pk>/', ESSSettingsViewSet.as_view(), name='ess-settings-detail'),
]

