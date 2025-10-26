"""
CRM module URL configuration.
"""
from django.urls import path, include
from .services.analytics_views import crm_analytics, crm_dashboard
from .services.reports_views import (
    pipeline_analysis,
    leads_analytics,
    campaign_performance
)

urlpatterns = [
    # CRM Analytics Endpoints
    path('analytics/', crm_analytics, name='crm-analytics'),
    path('dashboard/', crm_dashboard, name='crm-dashboard'),
    
    # CRM Reports Endpoints
    path('reports/pipeline-analysis/', pipeline_analysis, name='crm-pipeline-analysis'),
    path('reports/leads-analytics/', leads_analytics, name='crm-leads-analytics'),
    path('reports/campaign-performance/', campaign_performance, name='crm-campaign-performance'),
    
    # Include submodule URLs
    path('contacts/', include('crm.contacts.urls')),
    path('leads/', include('crm.leads.urls')),
    path('campaigns/', include('crm.campaigns.urls')),
    path('pipeline/', include('crm.pipeline.urls')),
]
