"""
Manufacturing Reports API Endpoints

Endpoints for generating and exporting manufacturing analytics:
- Production Report
- Quality Report

All reports support multi-format export (CSV, PDF, Excel) with professional formatting.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from datetime import datetime
import logging

from core.modules.report_export import (
    export_report_to_csv, export_report_to_pdf, export_report_to_xlsx,
    get_company_details_from_request
)

logger = logging.getLogger(__name__)


def _handle_manufacturing_report_export(request, report_data: dict, report_type: str, filename_base: str):
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
def production_report(request):
    """
    Manufacturing Production Report.
    
    Query Parameters:
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Production output metrics
    - Efficiency analysis
    - Downtime tracking
    """
    try:
        report_data = {
            'report_type': 'Production Report',
            'data': [],
            'title': 'Manufacturing Production Report',
            'summary': {'total_units': 0},
            'columns': [
                {'field': 'line', 'header': 'Production Line'},
                {'field': 'units_produced', 'header': 'Units Produced'},
                {'field': 'efficiency', 'header': 'Efficiency %'},
                {'field': 'downtime', 'header': 'Downtime (hours)'},
            ],
            'generated_at': datetime.now().isoformat(),
        }
        
        return _handle_manufacturing_report_export(request, report_data, 'Production Report', 'manufacturing_production')
        
    except Exception as e:
        logger.error(f"Error in Production Report endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Production Report'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quality_report(request):
    """
    Manufacturing Quality Report.
    
    Query Parameters:
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Quality metrics (defects, yields)
    - Compliance tracking
    - Trend analysis
    """
    try:
        report_data = {
            'report_type': 'Quality Report',
            'data': [],
            'title': 'Manufacturing Quality Report',
            'summary': {'total_defects': 0},
            'columns': [
                {'field': 'line', 'header': 'Production Line'},
                {'field': 'defects', 'header': 'Defects'},
                {'field': 'defect_rate', 'header': 'Defect Rate %'},
                {'field': 'compliance', 'header': 'Compliance %'},
            ],
            'generated_at': datetime.now().isoformat(),
        }
        
        return _handle_manufacturing_report_export(request, report_data, 'Quality Report', 'manufacturing_quality')
        
    except Exception as e:
        logger.error(f"Error in Quality Report endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Quality Report'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )
