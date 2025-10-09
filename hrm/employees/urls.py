from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from .views import employee_analytics

router = DefaultRouter()
router.register(r'employees', EmployeeViewSet)
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

urlpatterns = [
    path('', include(router.urls)),  # Remove the extra 'employees/' prefix
    path('upload-employee-data/', UploadEmployData.as_view(), name='upload-employee-data'),
    path('employee-status/', EmployeeStatusAPIView.as_view(), name='employee-status'),  # Remove extra 'employees/' prefix
    path('analytics/', employee_analytics, name='employee-analytics'),
]

