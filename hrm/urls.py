"""
HRM module main URL configuration.
"""
from django.urls import path, include
from .api import hrm_analytics

urlpatterns = [
    # HRM Analytics Endpoint
    path('analytics/', hrm_analytics, name='hrm-analytics'),
    
    # Include HRM submodule URLs
    path('payroll/', include('hrm.payroll.urls')),
    path('employees/', include('hrm.employees.urls')),
    path('attendance/', include('hrm.attendance.urls')),
    path('leave/', include('hrm.leave.urls')),
    path('payroll-settings/', include('hrm.payroll_settings.urls')),
]
