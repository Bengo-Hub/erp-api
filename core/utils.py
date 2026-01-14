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


def get_user_business(user):
    """
    Get the business associated with a user.

    Args:
        user: Django user object

    Returns:
        Business instance or None
    """
    if not user or not user.is_authenticated:
        return None

    try:
        from business.models import Bussiness

        # Check if user owns a business
        business = Bussiness.objects.filter(owner=user).first()
        if business:
            return business

        # Check if user is an employee
        from hrm.employees.models import Employee
        employee = Employee.objects.filter(user=user).select_related('branch__business').first()
        if employee and employee.branch:
            return employee.branch.business

        return None
    except Exception as e:
        logger.error(f"Error getting user business: {str(e)}", exc_info=True)
        return None


def get_user_branch(user, request=None):
    """
    Get the branch for a user. Logic:
    1. Check request header for X-Branch-ID
    2. Check if user is an employee with assigned branch
    3. For business owners/superusers, get the main branch or first branch

    Args:
        user: Django user object
        request: Optional Django request object for header-based branch

    Returns:
        Branch instance or None
    """
    if not user or not user.is_authenticated:
        return None

    try:
        from business.models import Branch, Bussiness

        # First check if branch is specified in request headers
        if request:
            branch_id = get_branch_id_from_request(request)
            if branch_id:
                branch = Branch.objects.filter(id=branch_id).first()
                if branch:
                    return branch

        # Check if user is an employee with assigned branch
        from hrm.employees.models import Employee
        employee = Employee.objects.filter(user=user).select_related('branch').first()
        if employee and employee.branch:
            return employee.branch

        # For business owners, get main branch or first branch
        business = get_user_business(user)
        if business:
            # First try to get main branch
            main_branch = Branch.objects.filter(business=business, is_main_branch=True).first()
            if main_branch:
                return main_branch
            # Fallback to first active branch
            first_branch = Branch.objects.filter(business=business, is_active=True).first()
            if first_branch:
                return first_branch

        # For superusers without a business, get any default/main branch
        if user.is_superuser:
            main_branch = Branch.objects.filter(is_main_branch=True).first()
            if main_branch:
                return main_branch
            # Fallback to first active branch
            return Branch.objects.filter(is_active=True).first()

        return None
    except Exception as e:
        logger.error(f"Error getting user branch: {str(e)}", exc_info=True)
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


def get_user_business_and_branch(request, return_objects=False):
    """
    Get the current user's business and branch context.
    Checks multiple sources in order of priority:
    1. Request headers/params (X-Business-ID, X-Branch-ID)
    2. User's business ownership
    3. User's employee assignment
    4. Default/main branch for superusers

    Args:
        request: Django request object
        return_objects: If True, return (Business, Branch) objects instead of IDs

    Returns:
        tuple: (business_id, branch_id) or (Business, Branch) if return_objects=True
               Returns (None, None) if context cannot be determined
    """
    try:
        user = getattr(request, 'user', None)

        # Try to get from request filters first
        if hasattr(request, 'filters'):
            business_id = request.filters.get('business_id')
            branch_id = request.filters.get('branch_id')
            if business_id and branch_id:
                if return_objects:
                    from business.models import Bussiness, Branch
                    business = Bussiness.objects.filter(id=business_id).first()
                    branch = Branch.objects.filter(id=branch_id).first()
                    return business, branch
                return business_id, branch_id

        # Try to extract from request headers/params
        business_id = get_business_id_from_request(request)
        branch_id = get_branch_id_from_request(request)

        # If we have both from headers, use them
        if business_id and branch_id:
            if return_objects:
                from business.models import Bussiness, Branch
                business = Bussiness.objects.filter(id=business_id).first()
                branch = Branch.objects.filter(id=branch_id).first()
                return business, branch
            return business_id, branch_id

        # Fall back to user context
        if user and user.is_authenticated:
            business = get_user_business(user)
            branch = get_user_branch(user, request)

            if return_objects:
                return business, branch

            return (
                business.id if business else business_id,
                branch.id if branch else branch_id
            )

        return (None, None)
    except Exception as e:
        logger.error(f"Error getting user business and branch: {str(e)}", exc_info=True)
        return (None, None)


def get_business_context(request):
    """
    Get complete business context for a request including objects.
    This is the main utility function for multi-tenant context resolution.

    Args:
        request: Django request object

    Returns:
        dict: {
            'business': Business instance or None,
            'branch': Branch instance or None,
            'business_id': int or None,
            'branch_id': int or None,
            'is_valid': bool - True if both business and branch are available
        }
    """
    business, branch = get_user_business_and_branch(request, return_objects=True)

    return {
        'business': business,
        'branch': branch,
        'business_id': business.id if business else None,
        'branch_id': branch.id if branch else None,
        'is_valid': bool(business and branch)
    }


def validate_business_context(request, business_id=None, branch_id=None):
    """
    Validate that the request has proper business context.
    If IDs not provided, attempts to resolve from request and user context.

    Args:
        request: Django request object
        business_id: Optional business ID to validate
        branch_id: Optional branch ID to validate

    Returns:
        dict: Validation result with business_id, branch_id, and is_valid
    """
    # If IDs not provided, try to resolve from context
    if not business_id or not branch_id:
        resolved_business_id, resolved_branch_id = get_user_business_and_branch(request)
        business_id = business_id or resolved_business_id
        branch_id = branch_id or resolved_branch_id

    return {
        'business_id': business_id,
        'branch_id': branch_id,
        'is_valid': bool(business_id and branch_id)
    }
