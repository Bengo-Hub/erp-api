"""
Filters for centralized error handling
"""
import django_filters
from django.db.models import Q
from .models import Error, ErrorSeverity, ErrorStatus, ErrorCategory


class ErrorFilter(django_filters.FilterSet):
    """Filter for errors"""
    
    # Status filters
    status = django_filters.ChoiceFilter(choices=ErrorStatus.choices)
    status_in = django_filters.BaseInFilter(field_name='status', lookup_expr='in')
    
    # Severity filters
    severity = django_filters.ChoiceFilter(choices=ErrorSeverity.choices)
    severity_in = django_filters.BaseInFilter(field_name='severity', lookup_expr='in')
    
    # Category filters
    category = django_filters.ChoiceFilter(choices=ErrorCategory.choices)
    category_in = django_filters.BaseInFilter(field_name='category', lookup_expr='in')
    
    # Module filters
    module = django_filters.CharFilter(lookup_expr='icontains')
    module_in = django_filters.BaseInFilter(field_name='module', lookup_expr='in')
    
    # User filters
    user = django_filters.NumberFilter()
    resolved_by = django_filters.NumberFilter()
    
    # Date filters
    occurred_after = django_filters.DateTimeFilter(field_name='occurred_at', lookup_expr='gte')
    occurred_before = django_filters.DateTimeFilter(field_name='occurred_at', lookup_expr='lte')
    resolved_after = django_filters.DateTimeFilter(field_name='resolved_at', lookup_expr='gte')
    resolved_before = django_filters.DateTimeFilter(field_name='resolved_at', lookup_expr='lte')
    
    # Occurrence filters
    occurrence_count_min = django_filters.NumberFilter(field_name='occurrence_count', lookup_expr='gte')
    occurrence_count_max = django_filters.NumberFilter(field_name='occurrence_count', lookup_expr='lte')
    
    # Search filters
    search = django_filters.CharFilter(method='filter_search')
    
    # Tag filters
    tags = django_filters.CharFilter(method='filter_tags')
    
    class Meta:
        model = Error
        fields = {
            'title': ['icontains', 'exact'],
            'description': ['icontains'],
            'error_message': ['icontains'],
            'function_name': ['icontains'],
        }
    
    def filter_search(self, queryset, name, value):
        """Search across multiple fields"""
        return queryset.filter(
            Q(title__icontains=value) |
            Q(description__icontains=value) |
            Q(module__icontains=value) |
            Q(error_message__icontains=value) |
            Q(function_name__icontains=value)
        )
    
    def filter_tags(self, queryset, name, value):
        """Filter by tags"""
        tags = [tag.strip() for tag in value.split(',')]
        return queryset.filter(tags__overlap=tags)
