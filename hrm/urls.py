"""
HRM module main URL configuration.
"""
from django.urls import path, include
from .api import hrm_analytics

urlpatterns = [
    # Analytics endpoints
    path('', hrm_analytics, name='hrm-analytics'),
]
