"""
Finance Analytics API Endpoints

Endpoints for generating and exporting financial analytics:
- Financial Analytics
- Finance Dashboard
- Tax Summary

All analytics support filtering by business, date range, and account types.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from datetime import datetime, date, timedelta
import logging

from core.utils import get_branch_id_from_request
from finance.analytics.finance_analytics import FinanceAnalyticsService

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def finance_analytics(request):
    """
    Get financial analytics for a specific period.
    
    Query Parameters:
    - period: 'week' | 'month' | 'quarter' | 'year' (default: month)
    - start_date: Start date (YYYY-MM-DD)
    - end_date: End date (YYYY-MM-DD)
    - business_id: Optional business filter
    
    Returns:
    - Revenue metrics
    - Expense breakdown
    - Cash flow analysis
    - Key financial indicators
    """
    try:
        period = request.query_params.get('period', 'month').lower()
        business_id = request.query_params.get('business_id')
        
        service = FinanceAnalyticsService()
        
        # Get financial summary for the period
        from datetime import timedelta
        from django.utils import timezone
        
        end_date = timezone.now().date()
        if period == 'week':
            start_date = end_date - timedelta(days=7)
        elif period == 'month':
            start_date = end_date - timedelta(days=30)
        elif period == 'quarter':
            start_date = end_date - timedelta(days=90)
        elif period == 'year':
            start_date = end_date - timedelta(days=365)
        else:
            start_date = end_date - timedelta(days=30)
        
        analytics_data = service.get_financial_summary(start_date, end_date, business_id)
        analytics_data['period'] = period
        analytics_data['generated_at'] = datetime.now().isoformat()
        
        return Response(analytics_data, status=http_status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error in finance analytics: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e)},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def finance_dashboard(request):
    """
    Get financial dashboard data.
    
    Query Parameters:
    - business_id: Optional business filter
    - period: Time period for analysis ('week', 'month', 'quarter', 'year')
    
    Returns:
    - Key financial metrics
    - Recent transactions
    - Account summaries
    - Cash position
    """
    try:
        business_id = request.query_params.get('business_id')
        period = request.query_params.get('period', 'month').lower()
        
        service = FinanceAnalyticsService()
        dashboard_data = service.get_finance_dashboard_data(
            business_id=business_id,
            period=period
        )
        
        return Response(dashboard_data, status=http_status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error in finance dashboard: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e)},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tax_summary(request):
    """
    Get tax summary report.
    
    Query Parameters:
    - year: Tax year (YYYY)
    - business_id: Optional business filter
    - tax_type: Optional specific tax type filter
    
    Returns:
    - Tax liabilities
    - Tax payments made
    - Tax due dates
    - Compliance status
    """
    try:
        year = request.query_params.get('year', str(date.today().year))
        business_id = request.query_params.get('business_id')
        
        # TODO: Implement tax summary calculation
        
        tax_data = {
            'year': year,
            'total_tax_liability': 0.0,
            'total_tax_paid': 0.0,
            'tax_due': 0.0,
            'compliance_status': 'pending',
            'generated_at': datetime.now().isoformat(),
        }
        
        return Response(tax_data, status=http_status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error in tax summary: {str(e)}", exc_info=True)
        return Response(
            {'error': str(e)},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )
