"""
HRM module main URL configuration.
"""
from django.urls import path, include
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from .api import hrm_analytics


@api_view(['GET'])
def hrm_root(request):
    """Return discoverable links for all HRM submodules."""
    def abs_path(relative):
        return request.build_absolute_uri(relative)
    
    return Response({
        "employees": abs_path('employees/'),
        "job_titles": abs_path('job-titles/'),
        "job_groups": abs_path('job-groups/'),
        "payroll": abs_path('payroll/'),
        "payroll_employees": abs_path('payroll/employees/'),
        "payroll_advances": abs_path('payroll/advances/'),
        "payroll_claims": abs_path('payroll/claims/'),
        "payroll_loss_damages": abs_path('payroll/losses-damages/'),
        "attendance": abs_path('attendance/'),
        "leave": abs_path('leave/'),
        "payroll_settings": abs_path('payroll-settings/'),
        "appraisals": abs_path('appraisals/'),
        "recruitment": abs_path('recruitment/'),
        "training": abs_path('training/'),
        "performance": abs_path('performance/'),
        "analytics": abs_path('analytics/'),
    })


urlpatterns = [
    path('', hrm_root, name='hrm-root'),
    path('analytics/', hrm_analytics, name='hrm-analytics'),
    
    # Legacy compatibility routes under /employees/ for payroll resources
    path('employees/', include((legacy_payroll_router.urls, 'hrm-legacy-payroll'))),
    
    # Include HRM submodule URLs
    path('', include('hrm.payroll.urls')),
    path('', include('hrm.employees.urls')),
    path('', include('hrm.attendance.urls')),
    path('', include('hrm.leave.urls')),
    path('', include('hrm.payroll_settings.urls')),
    path('', include('hrm.appraisals.urls')),
    path('', include('hrm.recruitment.urls')),
    path('', include('hrm.training.urls')),
    path('', include('hrm.performance.urls')),
]