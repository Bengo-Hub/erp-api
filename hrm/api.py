"""
HRM module main views for analytics and dashboard data.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from core.decorators import apply_common_filters
from .analytics.hrm_analytics import HrmAnalyticsService
import logging
logger = logging.getLogger(__name__)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@apply_common_filters
def hrm_analytics(request):
    """
    Get comprehensive HRM analytics data.
    
    Query Parameters:
    - period: Time period ('week', 'month', 'quarter', 'year', 'custom')
    - start_date: Custom start date (YYYY-MM-DD format, required if period='custom')
    - end_date: Custom end date (YYYY-MM-DD format, required if period='custom')
    - region_id: Region ID to filter data
    - department_id: Department ID to filter data
    
    Headers:
    - X-Branch-ID: Branch ID to filter data (automatically extracted)
    - X-Business-ID: Business ID to filter data (automatically extracted)
    """
    try:
        period = request.query_params.get('period', 'month')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        # Get filters from decorator
        filters = request.filters
        business_id = filters.get('business_id')
        region_id = filters.get('region_id')
        department_id = filters.get('department_id')
        branch_id = filters.get('branch_id')
        
        # Convert string dates to date objects if provided
        if start_date:
            try:
                from datetime import datetime
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            except ValueError:
                return Response({
                    'success': False,
                    'message': 'Invalid start_date format. Use YYYY-MM-DD',
                    'timestamp': timezone.now().isoformat()
                }, status=400)
        
        if end_date:
            try:
                from datetime import datetime
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                return Response({
                    'success': False,
                    'message': 'Invalid end_date format. Use YYYY-MM-DD',
                    'timestamp': timezone.now().isoformat()
                }, status=400)
        
        logger.info(f"HRM Analytics request - business_id: {business_id}, period: {period}, "
                   f"region_id: {region_id}, department_id: {department_id}, branch_id: {branch_id}")
        
        # Add more detailed logging
        logger.info(f"Request filters: {filters}")
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"Request query params: {dict(request.query_params)}")
        
        analytics_service = HrmAnalyticsService()
        data = analytics_service.get_hrm_dashboard_data(
            business_id=business_id,
            period=period,
            start_date=start_date,
            end_date=end_date,
            region_id=region_id,
            department_id=department_id,
            branch_id=branch_id
        )
        
        return Response({
            'success': True,
            'data': data,
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error fetching HRM analytics: {str(e)}")
        return Response({
            'success': False,
            'message': f'Error fetching HRM analytics: {str(e)}',
            'timestamp': timezone.now().isoformat()
        }, status=500)

