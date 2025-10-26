"""
Finance module utility functions and backward compatibility helpers.
"""
from datetime import datetime, timedelta
from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

# Import models from their canonical locations (single source of truth)
from finance.accounts.models import PaymentAccounts
from finance.payment.models import BillingDocument
from business.models import Branch
from finance.analytics.finance_analytics import FinanceAnalyticsService
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger('ditapi_logger')


def get_financial_summary(start_date, end_date, business_id=None):
    """
    Get financial summary for a date range.
    
    This is a wrapper around FinanceAnalyticsService.get_financial_summary()
    to maintain backward compatibility. Use the service method directly in new code.
    
    Args:
        start_date: Start date for filtering
        end_date: End date for filtering
        business_id: Optional business ID to filter by
    
    Returns:
        dict: Financial summary
    """
    analytics = FinanceAnalyticsService()
    return analytics.get_financial_summary(start_date, end_date, business_id)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def finance_branches(request):
    """
    Get business branches for finance reports.
    """
    try:
        correlation_id = get_correlation_id(request)
        business_name = request.query_params.get('business_name')
        
        if business_name:
            # Get branches for specific business
            branches = Branch.objects.filter(
                business__name__icontains=business_name,
                is_active=True
            ).select_related('business', 'location')
        else:
            # Get all active branches
            branches = Branch.objects.filter(is_active=True).select_related('business', 'location')
        
        branch_data = []
        for branch in branches:
            branch_data.append({
                'id': branch.id,
                'branch_code': branch.branch_code,
                'branch_name': branch.name,
                'business_name': branch.business.name,
                'city': branch.location.city,
                'county': branch.location.county,
                'constituency': branch.location.constituency,
                'ward': branch.location.ward,
                'street_name': branch.location.street_name,
                'building_name': branch.location.building_name,
                'state': str(branch.location.state) if branch.location.state else None,
                'country': str(branch.location.country) if branch.location.country else None,
                'contact_number': branch.contact_number,
                'email': branch.email,
                'is_main_branch': branch.is_main_branch,
                'is_active': branch.is_active
            })
        
        # Log branches access
        AuditTrail.log(
            operation=AuditTrail.VIEW,
            module='finance',
            entity_type='FinanceBranches',
            entity_id='branches',
            user=request.user,
            reason='Finance branches accessed',
            request=request
        )

        return APIResponse.success(
            data={
                'success': True,
                'results': branch_data,
                'count': len(branch_data)
            },
            message='Finance branches retrieved successfully',
            correlation_id=correlation_id
        )
    except Exception as e:
        logger.error(f"Error fetching branches: {str(e)}", exc_info=True)
        correlation_id = get_correlation_id(request)
        return APIResponse.server_error(
            message='Error fetching branches',
            error_id=str(e),
            correlation_id=correlation_id
        )
