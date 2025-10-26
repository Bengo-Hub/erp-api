"""
CRM Reports API Endpoints

Endpoints for generating and exporting comprehensive CRM analytics:
- Pipeline Analysis
- Leads Analytics
- Campaign Performance

All reports support multi-format export (CSV, PDF, Excel) with professional formatting.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from datetime import datetime, date, timedelta
import logging

from crm.services.report_formatters import CRMReportFormatter
from core.modules.report_export import (
    export_report_to_csv, export_report_to_pdf, export_report_to_xlsx,
    get_company_details_from_request
)

logger = logging.getLogger(__name__)


def _parse_date(date_str: str, default_offset_days: int = 0) -> date:
    """Parse date string in YYYY-MM-DD format."""
    if not date_str:
        return date.today() + timedelta(days=default_offset_days)
    
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        logger.warning(f"Could not parse date: {date_str}, using default")
        return date.today() + timedelta(days=default_offset_days)


def _handle_crm_report_export(request, report_data: dict, report_type: str, filename_base: str):
    """Helper function to handle report exports."""
    export_fmt = request.query_params.get('export', '').lower()
    
    if not export_fmt:
        return Response(report_data, status=http_status.HTTP_200_OK)
    
    company = get_company_details_from_request(request)
    data = report_data.get('data', [])
    title = report_data.get('title', report_type)
    filename = f"{filename_base}.{export_fmt}"
    
    try:
        if export_fmt == 'csv':
            return export_report_to_csv(data, filename=filename)
        elif export_fmt == 'pdf':
            return export_report_to_pdf(data, filename=filename, title=title, company=company)
        elif export_fmt == 'xlsx':
            return export_report_to_xlsx(data, filename=filename, title=title, company=company)
        else:
            return Response(
                {'error': f'Unsupported export format: {export_fmt}'},
                status=http_status.HTTP_400_BAD_REQUEST
            )
    except Exception as e:
        logger.error(f"Error exporting {report_type}: {str(e)}")
        return Response(
            {'error': f'Export failed: {str(e)}'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pipeline_analysis(request):
    """
    CRM Pipeline Analysis Report.
    
    Query Parameters:
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Sales pipeline by stage
    - Win rates and probabilities
    - Opportunity values and forecasts
    """
    try:
        business_id = request.query_params.get('business_id')
        report_data = CRMReportFormatter.generate_pipeline_analysis(business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_crm_report_export(request, report_data, 'CRM Pipeline Analysis', 'crm_pipeline')
        
    except Exception as e:
        logger.error(f"Error in Pipeline Analysis endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Pipeline Analysis'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def leads_analytics(request):
    """
    CRM Leads Analytics Report.
    
    Query Parameters:
    - start_date: Period start (YYYY-MM-DD, default: 30 days ago)
    - end_date: Period end (YYYY-MM-DD, default: today)
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Leads by source
    - Conversion rates
    - Lead quality scoring
    """
    try:
        end_date = _parse_date(request.query_params.get('end_date'))
        start_date = _parse_date(request.query_params.get('start_date'), default_offset_days=-30)
        
        if start_date > end_date:
            return Response(
                {'error': 'start_date must be before end_date'},
                status=http_status.HTTP_400_BAD_REQUEST
            )
        
        business_id = request.query_params.get('business_id')
        report_data = CRMReportFormatter.generate_leads_analytics(start_date, end_date, business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_crm_report_export(request, report_data, 'CRM Leads Analytics', 'crm_leads')
        
    except Exception as e:
        logger.error(f"Error in Leads Analytics endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Leads Analytics'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def campaign_performance(request):
    """
    CRM Campaign Performance Report.
    
    Query Parameters:
    - start_date: Period start (YYYY-MM-DD, default: 30 days ago)
    - end_date: Period end (YYYY-MM-DD, default: today)
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Campaign ROI analysis
    - Lead generation metrics
    - Budget vs. spend tracking
    """
    try:
        end_date = _parse_date(request.query_params.get('end_date'))
        start_date = _parse_date(request.query_params.get('start_date'), default_offset_days=-30)
        
        if start_date > end_date:
            return Response(
                {'error': 'start_date must be before end_date'},
                status=http_status.HTTP_400_BAD_REQUEST
            )
        
        business_id = request.query_params.get('business_id')
        report_data = CRMReportFormatter.generate_campaign_performance(start_date, end_date, business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_crm_report_export(request, report_data, 'Campaign Performance', 'crm_campaigns')
        
    except Exception as e:
        logger.error(f"Error in Campaign Performance endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Campaign Performance'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )
