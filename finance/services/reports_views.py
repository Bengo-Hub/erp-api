"""
Finance Reports API Endpoints

Endpoints for generating and exporting professional financial statements:
- Profit & Loss Statement
- Balance Sheet
- Cash Flow Statement

All reports support multi-format export (CSV, PDF, Excel) with professional formatting.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from datetime import datetime, date, timedelta
import logging

from finance.services.finance_report_formatters import FinanceReportFormatter
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


def _handle_finance_report_export(request, report_data: dict, report_type: str, filename_base: str):
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
def profit_and_loss_report(request):
    """
    Generate Profit & Loss Statement.
    
    Query Parameters:
    - start_date: Period start (YYYY-MM-DD, default: 30 days ago)
    - end_date: Period end (YYYY-MM-DD, default: today)
    - business_id: Business ID (optional)
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Revenue, COGS, margins, net income, comparison metrics
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
        report_data = FinanceReportFormatter.generate_p_and_l(start_date, end_date, business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_finance_report_export(request, report_data, 'Profit & Loss', 'p_and_l_report')
        
    except Exception as e:
        logger.error(f"Error in P&L report endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Profit & Loss Statement'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def balance_sheet_report(request):
    """
    Generate Balance Sheet.
    
    Query Parameters:
    - as_of_date: Balance sheet date (YYYY-MM-DD, default: today)
    - comparison_date: Comparison date (YYYY-MM-DD, default: 365 days prior)
    - business_id: Business ID (optional)
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Assets, liabilities, equity, changes, validation
    """
    try:
        as_of_date = _parse_date(request.query_params.get('as_of_date'))
        comparison_date = _parse_date(
            request.query_params.get('comparison_date'),
            default_offset_days=-365
        )
        
        business_id = request.query_params.get('business_id')
        report_data = FinanceReportFormatter.generate_balance_sheet(as_of_date, business_id, comparison_date)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_finance_report_export(request, report_data, 'Balance Sheet', 'balance_sheet_report')
        
    except Exception as e:
        logger.error(f"Error in Balance Sheet endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Balance Sheet'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def cash_flow_report(request):
    """
    Generate Cash Flow Statement.
    
    Query Parameters:
    - start_date: Period start (YYYY-MM-DD, default: 30 days ago)
    - end_date: Period end (YYYY-MM-DD, default: today)
    - business_id: Business ID (optional)
    - export: Export format (csv, pdf, xlsx)
    
    Returns:
    - Operating/investing/financing activities, net change
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
        report_data = FinanceReportFormatter.generate_cash_flow(start_date, end_date, business_id)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_finance_report_export(request, report_data, 'Cash Flow', 'cash_flow_report')
        
    except Exception as e:
        logger.error(f"Error in Cash Flow endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'report_type': 'Cash Flow Statement'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def financial_statements_suite(request):
    """
    Generate all Financial Statements (P&L, Balance Sheet, Cash Flow).
    
    Query Parameters:
    - start_date: Period start (YYYY-MM-DD, default: 30 days ago)
    - end_date: Period end (YYYY-MM-DD, default: today)
    - business_id: Business ID (optional)
    
    Returns:
    - Complete financial statement package
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
        statements = FinanceReportFormatter.generate_all_statements(start_date, end_date, business_id)
        
        for stmt_key, stmt_data in statements.items():
            if isinstance(stmt_data, dict) and 'error' in stmt_data:
                logger.warning(f"Error in {stmt_key}: {stmt_data.get('error')}")
        
        return Response(statements, status=http_status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error in Financial Statements Suite endpoint: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e), 'message': 'Failed to generate complete financial statement suite'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )
