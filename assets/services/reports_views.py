"""
Assets Reports API Endpoints

Endpoints for generating and exporting asset management analytics:
- Inventory Report
- Depreciation Report

All reports support multi-format export (CSV, PDF, Excel) with professional formatting.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from datetime import datetime
import logging

from assets.services.report_formatters import AssetsReportFormatter
from core.modules.report_export import (
    export_report_to_csv, export_report_to_pdf, export_report_to_xlsx,
    get_company_details_from_request
)

logger = logging.getLogger(__name__)


def _handle_assets_report_export(request, report_data: dict, report_type: str, filename_base: str):
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
def inventory_report(request):
    """
    Assets Inventory Report.
    
    Query Parameters:
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Asset inventory by category
    - Book value tracking
    - Depreciation schedule
    """
    try:
        business_id = request.query_params.get('business_id')
        report_data = AssetsReportFormatter.generate_inventory_report(business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_assets_report_export(request, report_data, 'Asset Inventory', 'assets_inventory')
        
    except Exception as e:
        logger.error(f"Error in Asset Inventory endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Asset Inventory'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def depreciation_report(request):
    """
    Assets Depreciation Report.
    
    Query Parameters:
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Depreciation by asset
    - Accumulated depreciation
    - Remaining useful life
    """
    try:
        business_id = request.query_params.get('business_id')
        report_data = AssetsReportFormatter.generate_depreciation_report(business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_assets_report_export(request, report_data, 'Depreciation Report', 'assets_depreciation')
        
    except Exception as e:
        logger.error(f"Error in Depreciation Report endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Depreciation Report'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )
