"""
HRM module main URL configuration.
"""
from django.urls import path, include
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .api import hrm_analytics


@api_view(['GET'])
def hrm_root(request):
    """Return discoverable links for all HRM submodules."""
    def abs_path(relative):
        return request.build_absolute_uri(relative)
    
    return Response({
        "employees": abs_path('employees/'),
        "contract-status": abs_path('contracts/status/'),
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
    
    # Include HRM submodule URLs
    path('payroll/', include('hrm.payroll.urls')),
    path('employees/', include('hrm.employees.urls')),
    path('attendance/', include('hrm.attendance.urls')),
    path('leave/', include('hrm.leave.urls')),
    path('payroll-settings/', include('hrm.payroll_settings.urls')),
    path('appraisals/', include('hrm.appraisals.urls')),
    path('recruitment/', include('hrm.recruitment.urls')),
    path('training/', include('hrm.training.urls')),
    path('performance/', include('hrm.performance.urls')),
]