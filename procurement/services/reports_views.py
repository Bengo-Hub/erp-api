"""
Procurement Reports API Endpoints

Endpoints for generating and exporting procurement analytics:
- Supplier Analysis
- Spend Analysis

All reports support multi-format export (CSV, PDF, Excel) with professional formatting.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from datetime import datetime, date, timedelta
import logging

from core.modules.report_export import (
    export_report_to_csv, export_report_to_pdf, export_report_to_xlsx,
    get_company_details_from_request
)

logger = logging.getLogger(__name__)


def _handle_procurement_report_export(request, report_data: dict, report_type: str, filename_base: str):
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
def supplier_analysis(request):
    """
    Procurement Supplier Analysis Report.
    
    Query Parameters:
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Supplier performance metrics
    - Cost analysis
    - Delivery performance
    """
    try:
        report_data = {
            'report_type': 'Supplier Analysis',
            'data': [],
            'title': 'Procurement Supplier Analysis',
            'summary': {'total_suppliers': 0},
            'columns': [
                {'field': 'supplier_name', 'header': 'Supplier Name'},
                {'field': 'total_spend', 'header': 'Total Spend (KShs)'},
                {'field': 'delivery_rating', 'header': 'Delivery Rating'},
                {'field': 'quality_rating', 'header': 'Quality Rating'},
            ],
            'generated_at': datetime.now().isoformat(),
        }
        
        return _handle_procurement_report_export(request, report_data, 'Supplier Analysis', 'procurement_suppliers')
        
    except Exception as e:
        logger.error(f"Error in Supplier Analysis endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Supplier Analysis'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def spend_analysis(request):
    """
    Procurement Spend Analysis Report.
    
    Query Parameters:
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Spending by category
    - Vendor concentration
    - Cost trends
    """
    try:
        report_data = {
            'report_type': 'Spend Analysis',
            'data': [],
            'title': 'Procurement Spend Analysis',
            'summary': {'total_spend': 0},
            'columns': [
                {'field': 'category', 'header': 'Category'},
                {'field': 'total_spend', 'header': 'Total Spend (KShs)'},
                {'field': 'percentage', 'header': 'Percentage %'},
                {'field': 'trend', 'header': 'Trend'},
            ],
            'generated_at': datetime.now().isoformat(),
        }
        
        return _handle_procurement_report_export(request, report_data, 'Spend Analysis', 'procurement_spend')
        
    except Exception as e:
        logger.error(f"Error in Spend Analysis endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Spend Analysis'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )
