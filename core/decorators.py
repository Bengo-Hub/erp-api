"""
Decorators for common view functionality.
"""

from functools import wraps
from django.http import JsonResponse
from django.utils import timezone
from .utils import get_branch_id_from_request, get_business_id_from_request, validate_business_context
import logging

logger = logging.getLogger(__name__)


def apply_common_filters(view_func):
    """
    Decorator to automatically apply common filters (business, branch, region, department)
    to views and add them to the request object.
    
    Usage:
    @apply_common_filters
    def my_view(request):
        filters = request.filters
        # Use filters['business_id'], filters['branch_id'], etc.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            # Extract filter parameters
            business_id = get_business_id_from_request(request)
            branch_id = get_branch_id_from_request(request)
            region_id = request.query_params.get('region_id')
            department_id = request.query_params.get('department_id')
            
            # Convert string IDs to integers if provided
            if region_id:
                try:
                    region_id = int(region_id)
                except ValueError:
                    return JsonResponse({
                        'success': False,
                        'message': 'Invalid region_id format',
                        'timestamp': timezone.now().isoformat()
                    }, status=400)
            
            if department_id:
                try:
                    department_id = int(department_id)
                except ValueError:
                    return JsonResponse({
                        'success': False,
                        'message': 'Invalid department_id format',
                        'timestamp': timezone.now().isoformat()
                    }, status=400)
            
            # Add filters to request object
            request.filters = {
                'business_id': business_id,
                'branch_id': branch_id,
                'region_id': region_id,
                'department_id': department_id
            }
            
            # Log the filters being applied
            logger.info(f"Applying filters to {view_func.__name__}: {request.filters}")
            
            return view_func(request, *args, **kwargs)
            
        except Exception as e:
            logger.error(f"Error applying common filters: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f'Error applying filters: {str(e)}',
                'timestamp': timezone.now().isoformat()
            }, status=500)
    
    return wrapper


def require_business_context(view_func):
    """
    Decorator to ensure that business context is available.
    Returns error if no business_id is found.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Apply common filters first
        if not hasattr(request, 'filters'):
            business_id = get_business_id_from_request(request)
            request.filters = {'business_id': business_id}
        
        if not request.filters.get('business_id'):
            return JsonResponse({
                'success': False,
                'message': 'Business context is required. Please provide business_id in query parameters or headers.',
                'timestamp': timezone.now().isoformat()
            }, status=400)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def require_branch_context(view_func):
    """
    Decorator to ensure that branch context is available.
    Returns error if no branch_id is found in headers.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Apply common filters first
        if not hasattr(request, 'filters'):
            branch_id = get_branch_id_from_request(request)
            request.filters = {'branch_id': branch_id}
        
        if not request.filters.get('branch_id'):
            return JsonResponse({
                'success': False,
                'message': 'Branch context is required. Provide X-Branch-ID header (branch id or branch_code).',
                'timestamp': timezone.now().isoformat()
            }, status=400)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def require_business_and_branch_context(view_func):
    """
    Decorator to ensure that both business and branch context are available.
    Returns error if either is missing.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Apply common filters first
        if not hasattr(request, 'filters'):
            business_id = get_business_id_from_request(request)
            branch_id = get_branch_id_from_request(request)
            request.filters = {'business_id': business_id, 'branch_id': branch_id}
        
        validation = validate_business_context(request, 
                                           request.filters.get('business_id'), 
                                           request.filters.get('branch_id'))
        
        if not validation['is_valid']:
            missing = []
            if not validation['business_id']:
                missing.append('business_id')
            if not validation['branch_id']:
                missing.append('X-Branch-ID header')
            
            return JsonResponse({
                'success': False,
                'message': f'Missing required context: {", ".join(missing)}',
                'timestamp': timezone.now().isoformat()
            }, status=400)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper
