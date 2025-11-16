"""
Centralized HRM Filter Utilities
Provides reusable filter parameter extraction and application for HRM ViewSets
"""
from core.utils import get_branch_id_from_request


def get_filter_params(request):
    """
    Extract standardized filter parameters from request.
    Supports multiple parameter formats: field[], field (multiple), field (single)
    
    Args:
        request: Django request object
        
    Returns:
        dict: Dictionary containing all extracted filter parameters
    """
    # Support multiple filter parameter formats
    department_ids = (
        request.query_params.getlist("department[]", None) or 
        request.query_params.getlist("department", None) or
        ([request.query_params.get("department")] if request.query_params.get("department") else None)
    )
    
    region_ids = (
        request.query_params.getlist("region[]", None) or 
        request.query_params.getlist("region", None) or
        ([request.query_params.get("region")] if request.query_params.get("region") else None)
    )
    
    project_ids = (
        request.query_params.getlist("project[]", None) or 
        request.query_params.getlist("project", None) or
        ([request.query_params.get("project")] if request.query_params.get("project") else None)
    )
    
    employee_ids = (
        request.query_params.getlist("employee_ids[]", None) or
        request.query_params.getlist("employee_ids", None) or
        request.query_params.getlist("employee", None) or
        ([request.query_params.get("employee")] if request.query_params.get("employee") else None)
    )
    
    # Get branch from X-Branch-ID header
    branch_id = get_branch_id_from_request(request)
    if not branch_id:
        # Fallback to query param
        branch_id = request.query_params.get('branch_id', None) or request.query_params.get('branch', None)
    
    # Filter out None/empty and coerce to integers where applicable (ignore invalid tokens)
    def to_int_list(values):
        if not values:
            return None
        result = []
        for v in values:
            if v in (None, '', 'null', 'None'):
                continue
            try:
                result.append(int(v))
            except (TypeError, ValueError):
                # Ignore non-integer values to prevent errors like "expected a number but got 'advances'"
                continue
        return result or None

    department_ids = to_int_list(department_ids)
    region_ids = to_int_list(region_ids)
    project_ids = to_int_list(project_ids)
    employee_ids = to_int_list(employee_ids)
    
    return {
        'branch_id': branch_id,
        'department_ids': department_ids if department_ids else None,
        'region_ids': region_ids if region_ids else None,
        'project_ids': project_ids if project_ids else None,
        'employee_ids': employee_ids if employee_ids else None,
    }


def apply_hrm_filters(queryset, filter_params, filter_prefix='employee__hr_details'):
    """
    Apply HRM filters to a queryset.
    
    Args:
        queryset: Django QuerySet to filter
        filter_params: Dictionary of filter parameters from get_filter_params()
        filter_prefix: Prefix for filter fields (default: 'employee__hr_details')
                      Use '' for direct filtering (e.g., HRDetails model)
                      Use 'employee__hr_details' for employee-related models
        
    Returns:
        QuerySet: Filtered queryset
    """
    # Apply branch filter
    if filter_params.get('branch_id'):
        if filter_prefix:
            queryset = queryset.filter(**{f"{filter_prefix}__branch_id": filter_params['branch_id']})
        else:
            queryset = queryset.filter(branch_id=filter_params['branch_id'])
    
    # Apply department filter
    if filter_params.get('department_ids'):
        if filter_prefix:
            queryset = queryset.filter(**{f"{filter_prefix}__department_id__in": filter_params['department_ids']})
        else:
            queryset = queryset.filter(department_id__in=filter_params['department_ids'])
    
    # Apply region filter
    if filter_params.get('region_ids'):
        if filter_prefix:
            queryset = queryset.filter(**{f"{filter_prefix}__region_id__in": filter_params['region_ids']})
        else:
            queryset = queryset.filter(region_id__in=filter_params['region_ids'])
    
    # Apply project filter
    if filter_params.get('project_ids'):
        if filter_prefix:
            queryset = queryset.filter(**{f"{filter_prefix}__project_id__in": filter_params['project_ids']})
        else:
            queryset = queryset.filter(project_id__in=filter_params['project_ids'])
    
    # Apply employee filter
    if filter_params.get('employee_ids'):
        if filter_prefix:
            # Extract just 'employee' from the prefix
            employee_prefix = filter_prefix.split('__')[0] if '__' in filter_prefix else 'employee'
            queryset = queryset.filter(**{f"{employee_prefix}__id__in": filter_params['employee_ids']})
        else:
            queryset = queryset.filter(id__in=filter_params['employee_ids'])
    
    return queryset


def apply_employee_filters(queryset, filter_params):
    """
    Apply HRM filters directly to Employee queryset.
    Convenience wrapper for apply_hrm_filters with correct prefix.
    
    Args:
        queryset: Employee QuerySet to filter
        filter_params: Dictionary of filter parameters from get_filter_params()
        
    Returns:
        QuerySet: Filtered employee queryset
    """
    # Apply branch filter
    if filter_params.get('branch_id'):
        queryset = queryset.filter(hr_details__branch_id=filter_params['branch_id'])
    
    # Apply department filter
    if filter_params.get('department_ids'):
        queryset = queryset.filter(hr_details__department_id__in=filter_params['department_ids'])
    
    # Apply region filter
    if filter_params.get('region_ids'):
        queryset = queryset.filter(hr_details__region_id__in=filter_params['region_ids'])
    
    # Apply project filter
    if filter_params.get('project_ids'):
        queryset = queryset.filter(hr_details__project_id__in=filter_params['project_ids'])
    
    # Apply employee IDs filter
    if filter_params.get('employee_ids'):
        queryset = queryset.filter(id__in=filter_params['employee_ids'])
    
    return queryset

