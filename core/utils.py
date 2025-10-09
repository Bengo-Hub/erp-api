"""
Core utility functions for the ERP system.
"""
import logging

logger = logging.getLogger(__name__)

def get_branch_id_from_request(request):
    """
    Extract branch ID from request headers.
    
    Args:
        request: Django request object
        
    Returns:
        int or None: Branch ID if found in headers, None otherwise
    """
    try:
        # Check for X-Branch-ID header (from axios)
        branch_id = request.headers.get('X-Branch-ID')
        if branch_id:
            # Try to convert to integer first (if it's a branch ID)
            try:
                logger.info(f"Branch ID: {branch_id}")
                return int(branch_id)
            except ValueError:
                # If it's not an integer, it might be a branch_code
                # Try to find the branch by branch_code
                from business.models import Branch
                try:
                    branch = Branch.objects.get(branch_code=branch_id)
                    logger.info(f"Branch ID: {branch.id}")
                    return branch.id
                except Branch.DoesNotExist:
                    return None
        
        # Fallback to HTTP_X_BRANCH_ID (Django converts headers)
        branch_id = request.META.get('HTTP_X_BRANCH_ID')
        if branch_id:
            try:
                logger.info(f"Branch ID: {branch_id}")
                return int(branch_id)
            except ValueError:
                # If it's not an integer, it might be a branch_code
                from business.models import Branch
                try:
                    branch = Branch.objects.get(branch_code=branch_id)
                    logger.info(f"Branch ID: {branch.id}")
                    return branch.id
                except Branch.DoesNotExist:
                    return None
        
        return None
    except (ValueError, TypeError):
        return None


def get_branch_by_code(branch_code):
    """
    Get branch ID from branch_code.
    
    Args:
        branch_code: Branch code string
        
    Returns:
        int or None: Branch ID if found, None otherwise
    """
    try:
        from business.models import Branch
        branch = Branch.objects.get(branch_code=branch_code)
        return branch.id
    except Branch.DoesNotExist:
        return None


def get_business_id_from_request(request):
    """
    Extract business ID from request headers or query parameters.
    
    Args:
        request: Django request object
        
    Returns:
        int or None: Business ID if found, None otherwise
    """
    try:
        # Check query parameters first
        business_id = request.query_params.get('business_id')
        if business_id:
            return int(business_id)
        
        # Check headers
        business_id = request.headers.get('X-Business-ID')
        if business_id:
            return int(business_id)
        
        # Fallback to META
        business_id = request.META.get('HTTP_X_BUSINESS_ID')
        if business_id:
            logger.info(f"Business ID: {business_id}")
            return int(business_id)
        
        return None
    except (ValueError, TypeError):
        return None


def apply_filters_to_queryset(queryset, filters):
    """
    Apply common filters to a queryset.
    
    Args:
        queryset: Django queryset
        filters: dict containing filter parameters
        
    Returns:
        Django queryset: Filtered queryset
    """
    if not filters:
        return queryset
    
    # Apply business filter
    if filters.get('business_id'):
        if hasattr(queryset.model, 'organisation'):
            queryset = queryset.filter(organisation_id=filters['business_id'])
        elif hasattr(queryset.model, 'employee__organisation'):
            queryset = queryset.filter(employee__organisation__id=filters['business_id'])
        elif hasattr(queryset.model, 'business'):
            queryset = queryset.filter(business_id=filters['business_id'])
    
    # Apply branch filter
    if filters.get('branch_id'):
        if hasattr(queryset.model, 'hr_details__branch'):
            queryset = queryset.filter(hr_details__branch__id=filters['branch_id'])
        elif hasattr(queryset.model, 'employee__hr_details__branch'):
            queryset = queryset.filter(employee__hr_details__branch__id=filters['branch_id'])
        elif hasattr(queryset.model, 'branch'):
            queryset = queryset.filter(branch__id=filters['branch_id'])
    
    # Apply region filter
    if filters.get('region_id'):
        if hasattr(queryset.model, 'hr_details__region'):
            queryset = queryset.filter(hr_details__region__id=filters['region_id'])
        elif hasattr(queryset.model, 'employee__hr_details__region'):
            queryset = queryset.filter(employee__hr_details__region__id=filters['region_id'])
        elif hasattr(queryset.model, 'region'):
            queryset = queryset.filter(region__id=filters['region_id'])
    
    # Apply department filter
    if filters.get('department_id'):
        if hasattr(queryset.model, 'hr_details__department'):
            queryset = queryset.filter(hr_details__department__id=filters['department_id'])
        elif hasattr(queryset.model, 'employee__hr_details__department'):
            queryset = queryset.filter(employee__hr_details__department__id=filters['department_id'])
        elif hasattr(queryset.model, 'department'):
            queryset = queryset.filter(department__id=filters['department_id'])
    
    return queryset


def get_user_business_and_branch(request):
    """
    Get the current user's business and branch context.
    
    Args:
        request: Django request object
        
    Returns:
        tuple: (business_id, branch_id) or (None, None)
    """
    try:
        # Try to get from request filters first
        if hasattr(request, 'filters'):
            return request.filters.get('business_id'), request.filters.get('branch_id')
        
        # Extract from request
        business_id = get_business_id_from_request(request)
        branch_id = get_branch_id_from_request(request)
        
        return business_id, branch_id
    except Exception:
        return None, None


def validate_business_context(request, business_id=None, branch_id=None):
    """
    Validate that the request has proper business context.
    
    Args:
        request: Django request object
        business_id: Optional business ID to validate
        branch_id: Optional branch ID to validate
        
    Returns:
        dict: Validation result with business_id and branch_id
    """
    if not business_id:
        business_id = get_business_id_from_request(request)
    
    if not branch_id:
        branch_id = get_branch_id_from_request(request)
    
    return {
        'business_id': business_id,
        'branch_id': branch_id,
        'is_valid': bool(business_id and branch_id)
    }
