"""
Lean view endpoints for payroll reports.
Each endpoint delegates to PayrollReportsService for business logic.
"""
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from django.utils import timezone
from datetime import datetime
import logging

from .services.reports_service import PayrollReportsService
from core.utils import get_branch_id_from_request
from core.modules.report_export import (
    export_report_to_csv, export_report_to_pdf, export_report_to_xlsx,
    get_company_details_from_request
)
from rest_framework import viewsets
from .models import Payslip
from .serializers import *

logger = logging.getLogger(__name__)


def _handle_report_export(request, report_data, report_type, filename_base):
    """
    Helper function to handle report exports in multiple formats.
    
    Args:
        request: HTTP request
        report_data: Report data dict from service
        report_type: Type of report (for title)
        filename_base: Base filename (without extension)
    
    Returns:
        Response with exported data or JSON
    """
    export_fmt = request.query_params.get('export', '').lower()
    
    if not export_fmt:
        return Response(report_data, status=http_status.HTTP_200_OK)
    
    # Get company details for headers
    company = get_company_details_from_request(request)
    data = report_data.get('data', [])
    totals = report_data.get('totals', {})
    title = report_data.get('title', report_type)
    filename = f"{filename_base}.{export_fmt}"
    
    try:
        if export_fmt == 'csv':
            return export_report_to_csv(data, filename=filename, include_summary=bool(totals), summary_data=totals)
        elif export_fmt == 'pdf':
            return export_report_to_pdf(data, filename=filename, title=title, company=company)
        elif export_fmt == 'xlsx':
            return export_report_to_xlsx(data, filename=filename, title=title, company=company, include_summary=bool(totals), summary_data=totals)
        else:
            return Response({'error': f'Unsupported export format: {export_fmt}'}, status=http_status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error exporting report as {export_fmt}: {str(e)}")
        return Response({'error': f'Export failed: {str(e)}'}, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def p9_tax_report(request):
    """
    Generate P9 Tax Deduction Card report.
    
    Query Parameters:
    - payment_period: YYYY-MM-DD format (optional)
    - year: YYYY format (optional, used if payment_period not provided)
    - month: MM format (optional, requires year)
    - employee_ids: Comma-separated employee IDs (optional)
    - department_ids: Comma-separated department IDs (optional)
    - branch_id: Branch ID (optional)
    - export: Export format (csv, pdf, xlsx)
    """
    try:
        filters = _extract_filters(request)
        reports_service = PayrollReportsService()
        report_data = reports_service.generate_p9_report(filters)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_report_export(request, report_data, 'P9 Tax Deduction Card', 'p9_report')
        
    except Exception as e:
        logger.error(f"Error in P9 report endpoint: {str(e)}")
        return Response({
            'error': str(e),
            'report_type': 'P9'
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def p10a_employer_return(request):
    """
    Generate P10A Employer Return of Employees (Annual tax return).
    
    Query Parameters:
    - year: YYYY format (required)
    - employee_ids: Comma-separated employee IDs (optional)
    - department_ids: Comma-separated department IDs (optional)
    - branch_id: Branch ID (optional)
    - export: Export format (csv, pdf, xlsx)
    """
    try:
        filters = _extract_filters(request)
        reports_service = PayrollReportsService()
        report_data = reports_service.generate_p10a_report(filters)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_report_export(request, report_data, 'P10A Employer Return', 'p10a_report')
        
    except Exception as e:
        logger.error(f"Error in P10A report endpoint: {str(e)}")
        return Response({
            'error': str(e),
            'report_type': 'P10A'
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def statutory_deductions_report(request):
    """
    Generate Statutory Deductions report (NSSF, NHIF, etc).
    
    Query Parameters:
    - deduction_type: 'nssf' or 'nhif' (default: 'nssf')
    - payment_period: YYYY-MM-DD format (optional)
    - year: YYYY format (optional)
    - month: MM format (optional, requires year)
    - export: Export format (csv, pdf, xlsx)
    """
    try:
        filters = _extract_filters(request)
        deduction = filters.get('deduction_type', 'nssf')
        reports_service = PayrollReportsService()
        report_data = reports_service.generate_statutory_deductions_report(filters, deduction)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_report_export(request, report_data, f'{deduction.upper()} Deductions', f'{deduction}_report')
        
    except Exception as e:
        logger.error(f"Error in statutory deductions report: {str(e)}")
        return Response({
            'error': str(e),
            'report_type': 'Statutory Deductions'
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def bank_net_pay_report(request):
    """
    Generate Bank Net Pay report for salary transfers.
    
    Query Parameters:
    - payment_period: YYYY-MM-DD format (optional)
    - bank: Bank name/ID (optional)
    - export: Export format (csv, pdf, xlsx)
    """
    try:
        filters = _extract_filters(request)
        reports_service = PayrollReportsService()
        report_data = reports_service.generate_bank_net_pay_report(filters)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_report_export(request, report_data, 'Bank Net Pay Report', 'bank_net_pay')
        
    except Exception as e:
        logger.error(f"Error in bank net pay report: {str(e)}")
        return Response({
            'error': str(e),
            'report_type': 'Bank Net Pay'
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def muster_roll_report(request):
    """
    Generate Muster Roll report showing all employee payroll details.
    
    Query Parameters:
    - payment_period: YYYY-MM-DD format (optional)
    - export: Export format (csv, pdf, xlsx)
    """
    try:
        filters = _extract_filters(request)
        reports_service = PayrollReportsService()
        report_data = reports_service.generate_muster_roll_report(filters)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_report_export(request, report_data, 'Muster Roll Report', 'muster_roll')
        
    except Exception as e:
        logger.error(f"Error in muster roll report: {str(e)}")
        return Response({
            'error': str(e),
            'report_type': 'Muster Roll'
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def withholding_tax_report(request):
    """
    Generate Withholding Tax report.
    
    Query Parameters:
    - payment_period: YYYY-MM-DD format (optional)
    - export: Export format (csv, pdf, xlsx)
    """
    try:
        filters = _extract_filters(request)
        reports_service = PayrollReportsService()
        report_data = reports_service.generate_withholding_tax_report(filters)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_report_export(request, report_data, 'Withholding Tax Report', 'withholding_tax')
        
    except Exception as e:
        logger.error(f"Error in withholding tax report: {str(e)}")
        return Response({
            'error': str(e),
            'report_type': 'Withholding Tax'
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def variance_report(request):
    """
    Generate Payroll Variance report comparing two periods.
    
    Query Parameters:
    - period1: YYYY-MM-DD format (start period)
    - period2: YYYY-MM-DD format (comparison period)
    - export: Export format (csv, pdf, xlsx)
    """
    try:
        filters = _extract_filters(request)
        reports_service = PayrollReportsService()
        report_data = reports_service.generate_variance_report(filters)
        
        if 'error' in report_data:
            return Response(report_data, status=http_status.HTTP_400_BAD_REQUEST)
        
        return _handle_report_export(request, report_data, 'Variance Report', 'variance_report')
        
    except Exception as e:
        logger.error(f"Error in variance report: {str(e)}")
        return Response({
            'error': str(e),
            'report_type': 'Variance'
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


def _extract_filters(request) -> dict:
    """
    Helper function to extract and parse filters from request query parameters.
    Keeps view code DRY.
    """
    filters = {}
    
    # Date filters
    payment_period = request.query_params.get('payment_period')
    if payment_period:
        try:
            filters['payment_period'] = datetime.strptime(payment_period, '%Y-%m-%d').date()
        except ValueError:
            # Invalid date format; skip this filter silently
            pass
    
    current_period = request.query_params.get('current_period')
    if current_period:
        try:
            filters['current_period'] = datetime.strptime(current_period, '%Y-%m-%d').date()
        except ValueError:
            # Invalid date format; skip this filter silently
            pass
    
    previous_period = request.query_params.get('previous_period')
    if previous_period:
        try:
            filters['previous_period'] = datetime.strptime(previous_period, '%Y-%m-%d').date()
        except ValueError:
            # Invalid date format; skip this filter silently
            pass
    
    year = request.query_params.get('year')
    if year:
        try:
            filters['year'] = int(year)
        except ValueError:
            # Invalid year format; skip this filter silently
            pass
    
    month = request.query_params.get('month')
    if month:
        try:
            filters['month'] = int(month)
        except ValueError:
            # Invalid month format; skip this filter silently
            pass
    
    # ID filters (comma-separated lists)
    employee_ids = request.query_params.get('employee_ids')
    if employee_ids:
        try:
            filters['employee_ids'] = [int(id.strip()) for id in employee_ids.split(',')]
        except ValueError:
            # Invalid employee IDs; skip this filter silently
            pass
    
    department_ids = request.query_params.get('department_ids')
    if department_ids:
        try:
            filters['department_ids'] = [int(id.strip()) for id in department_ids.split(',')]
        except ValueError:
            # Invalid department IDs; skip this filter silently
            pass
    
    region_ids = request.query_params.get('region_ids')
    if region_ids:
        try:
            filters['region_ids'] = [int(id.strip()) for id in region_ids.split(',')]
        except ValueError:
            # Invalid region IDs; skip this filter silently
            pass
    
    # Single ID filters
    # Prefer explicit query param, else resolve from X-Branch-ID header (id or branch_code)
    branch_id = request.query_params.get('branch_id')
    if branch_id:
        try:
            filters['branch_id'] = int(branch_id)
        except ValueError:
            # Invalid branch_id; skip this filter silently
            pass
    else:
        header_branch_id = get_branch_id_from_request(request)
        if header_branch_id:
            filters['branch_id'] = header_branch_id

    # Optional branch_code support
    branch_code = request.query_params.get('branch_code')
    if branch_code and 'branch_id' not in filters:
        try:
            from business.models import Branch
            branch = Branch.objects.get(branch_code=branch_code)
            filters['branch_id'] = branch.id
        except Exception:
            pass
    
    # Status filter
    payroll_status = request.query_params.get('payroll_status')
    if payroll_status:
        filters['payroll_status'] = payroll_status
    
    return filters

