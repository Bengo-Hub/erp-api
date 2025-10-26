"""
Standardized pagination configuration for BengoBox ERP
All API responses that return array-based data must use this pagination format:
{
    "count": <total_records>,
    "next": <url_to_next_page>,
    "previous": <url_to_previous_page>,
    "results": [...]
}
"""
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultPagination(PageNumberPagination):
    """
    Standard pagination class for all ERP modules
    - 100 records per page by default
    - Consistent response format across all endpoints
    - Supports custom page_size via query parameter
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000
    page_query_param = 'page'

    def get_paginated_response(self, data):
        """
        Standardized paginated response format
        """
        return Response({
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
            'page_size': self.page_size,
            'page': self.page.number,
            'total_pages': self.page.paginator.num_pages
        })


def paginated_response(queryset, serializer_class, request, view):
    """
    Helper function to create paginated responses
    Usage in custom list() methods:
    
    from core.pagination import paginated_response
    
    def list(self, request):
        queryset = MyModel.objects.all()
        # Apply filters
        return paginated_response(queryset, MySerializer, request, self)
    """
    paginator = StandardResultPagination()
    page = paginator.paginate_queryset(queryset, request, view=view)
    
    if page is not None:
        serializer = serializer_class(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)
    
    # Fallback if pagination not available
    serializer = serializer_class(queryset, many=True, context={'request': request})
    return Response({
        'count': len(serializer.data),
        'next': None,
        'previous': None,
        'results': serializer.data
    })


def ensure_paginated_format(data):
    """
    Ensure response data is in paginated format
    Useful for wrapping non-paginated responses
    """
    if isinstance(data, dict) and 'results' in data:
        # Already paginated
        return data
    
    if isinstance(data, list):
        # Wrap list in paginated format
        return {
            'count': len(data),
            'next': None,
            'previous': None,
            'results': data
        }
    
    # Single object or other format
    return data

