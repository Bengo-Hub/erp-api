"""
E-commerce Reports API Endpoints

Endpoints for generating and exporting comprehensive e-commerce analytics:
- Sales Dashboard
- Product Performance
- Customer Analysis
- Inventory Management

All reports support multi-format export (CSV, PDF, Excel) with professional formatting.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from datetime import datetime, date, timedelta
import logging

from ecommerce.services.report_formatters import EcommerceReportFormatter
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


def _handle_ecommerce_report_export(request, report_data: dict, report_type: str, filename_base: str):
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
def sales_dashboard(request):
    """
    Generate Sales Dashboard with trend analysis.
    
    Query Parameters:
    - start_date: Period start (YYYY-MM-DD, default: 30 days ago)
    - end_date: Period end (YYYY-MM-DD, default: today)
    - period_type: 'daily', 'weekly', 'monthly' (default: daily)
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Sales metrics, growth analysis, daily breakdown
    """
    try:
        end_date = _parse_date(request.query_params.get('end_date'))
        start_date = _parse_date(request.query_params.get('start_date'), default_offset_days=-30)
        
        if start_date > end_date:
            return Response(
                {'error': 'start_date must be before end_date'},
                status=http_status.HTTP_400_BAD_REQUEST
            )
        
        period_type = request.query_params.get('period_type', 'daily').lower()
        business_id = request.query_params.get('business_id')
        
        report_data = EcommerceReportFormatter.generate_sales_dashboard(start_date, end_date, period_type, business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_ecommerce_report_export(request, report_data, 'Sales Dashboard', 'sales_dashboard')
        
    except Exception as e:
        logger.error(f"Error in Sales Dashboard endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Sales Dashboard'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_performance(request):
    """
    Generate Product Performance Report.
    
    Query Parameters:
    - start_date: Period start (YYYY-MM-DD, default: 30 days ago)
    - end_date: Period end (YYYY-MM-DD, default: today)
    - top_n: Top N products (default: 50)
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Top products by revenue, sales quantity, margin analysis
    """
    try:
        end_date = _parse_date(request.query_params.get('end_date'))
        start_date = _parse_date(request.query_params.get('start_date'), default_offset_days=-30)
        
        if start_date > end_date:
            return Response(
                {'error': 'start_date must be before end_date'},
                status=http_status.HTTP_400_BAD_REQUEST
            )
        
        top_n = int(request.query_params.get('top_n', 50))
        business_id = request.query_params.get('business_id')
        
        report_data = EcommerceReportFormatter.generate_product_performance(start_date, end_date, top_n, business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_ecommerce_report_export(request, report_data, 'Product Performance', 'product_performance')
        
    except Exception as e:
        logger.error(f"Error in Product Performance endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Product Performance'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_analysis(request):
    """
    Generate Customer Analysis Report.
    
    Query Parameters:
    - start_date: Period start (YYYY-MM-DD, default: 30 days ago)
    - end_date: Period end (YYYY-MM-DD, default: today)
    - min_orders: Minimum orders (default: 1)
    - business_id: Optional business filter
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Customer lifetime value analysis, segmentation
    """
    try:
        end_date = _parse_date(request.query_params.get('end_date'))
        start_date = _parse_date(request.query_params.get('start_date'), default_offset_days=-30)
        
        if start_date > end_date:
            return Response(
                {'error': 'start_date must be before end_date'},
                status=http_status.HTTP_400_BAD_REQUEST
            )
        
        min_orders = int(request.query_params.get('min_orders', 1))
        business_id = request.query_params.get('business_id')
        
        report_data = EcommerceReportFormatter.generate_customer_analysis(start_date, end_date, min_orders, business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_ecommerce_report_export(request, report_data, 'Customer Analysis', 'customer_analysis')
        
    except Exception as e:
        logger.error(f"Error in Customer Analysis endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Customer Analysis'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def inventory_management(request):
    """
    Generate Inventory Management Report.
    
    Query Parameters:
    - business_id: Optional business filter
    - include_low_stock: Include low stock items (default: true)
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Current stock levels, reorder status, inventory value
    """
    try:
        business_id = request.query_params.get('business_id')
        
        report_data = EcommerceReportFormatter.generate_inventory_report(business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_ecommerce_report_export(request, report_data, 'Inventory Management', 'inventory_management')
        
    except Exception as e:
        logger.error(f"Error in Inventory Management endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Inventory Management'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ecommerce_reports_suite(request):
    """
    Generate all E-commerce Reports (complete suite).
    
    Query Parameters:
    - start_date: Period start (YYYY-MM-DD, default: 30 days ago)
    - end_date: Period end (YYYY-MM-DD, default: today)
    - business_id: Optional business filter
    
    Returns:
    - Complete e-commerce analytics package
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
        reports = EcommerceReportFormatter.generate_all_reports(start_date, end_date, business_id)
        
        for report_key, report_data in reports.items():
            if isinstance(report_data, dict) and 'error' in report_data:
                logger.warning(f"Error in {report_key}: {report_data.get('error')}")
        
        return Response(reports, status=http_status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error in E-commerce Reports Suite endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'message': 'Failed to generate complete e-commerce reports suite'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )
