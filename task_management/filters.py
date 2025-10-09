"""
Filters for centralized task management
"""
import django_filters
from django.db.models import Q
from .models import Task, TaskStatus, TaskType, TaskPriority


class TaskFilter(django_filters.FilterSet):
    """Filter for tasks"""
    
    # Status filters
    status = django_filters.ChoiceFilter(choices=TaskStatus.choices)
    status_in = django_filters.BaseInFilter(field_name='status', lookup_expr='in')
    
    # Type filters
    task_type = django_filters.ChoiceFilter(choices=TaskType.choices)
    task_type_in = django_filters.BaseInFilter(field_name='task_type', lookup_expr='in')
    
    # Priority filters
    priority = django_filters.ChoiceFilter(choices=TaskPriority.choices)
    priority_in = django_filters.BaseInFilter(field_name='priority', lookup_expr='in')
    
    # Module filters
    module = django_filters.CharFilter(lookup_expr='icontains')
    module_in = django_filters.BaseInFilter(field_name='module', lookup_expr='in')
    
    # User filters
    created_by = django_filters.NumberFilter()
    assigned_to = django_filters.NumberFilter()
    
    # Date filters
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    started_after = django_filters.DateTimeFilter(field_name='started_at', lookup_expr='gte')
    started_before = django_filters.DateTimeFilter(field_name='started_at', lookup_expr='lte')
    completed_after = django_filters.DateTimeFilter(field_name='completed_at', lookup_expr='gte')
    completed_before = django_filters.DateTimeFilter(field_name='completed_at', lookup_expr='lte')
    
    # Progress filters
    progress_min = django_filters.NumberFilter(field_name='progress', lookup_expr='gte')
    progress_max = django_filters.NumberFilter(field_name='progress', lookup_expr='lte')
    
    # Duration filters
    duration_min = django_filters.DurationFilter(method='filter_duration_min')
    duration_max = django_filters.DurationFilter(method='filter_duration_max')
    
    # Search filters
    search = django_filters.CharFilter(method='filter_search')
    
    # Tag filters
    tags = django_filters.CharFilter(method='filter_tags')
    
    class Meta:
        model = Task
        fields = {
            'title': ['icontains', 'exact'],
            'description': ['icontains'],
        }
    
    def filter_duration_min(self, queryset, name, value):
        """Filter by minimum duration"""
        return queryset.filter(
            Q(started_at__isnull=False) & Q(completed_at__isnull=False),
            completed_at__gte=models.F('started_at') + value
        )
    
    def filter_duration_max(self, queryset, name, value):
        """Filter by maximum duration"""
        return queryset.filter(
            Q(started_at__isnull=False) & Q(completed_at__isnull=False),
            completed_at__lte=models.F('started_at') + value
        )
    
    def filter_search(self, queryset, name, value):
        """Search across multiple fields"""
        return queryset.filter(
            Q(title__icontains=value) |
            Q(description__icontains=value) |
            Q(module__icontains=value) |
            Q(task_type__icontains=value)
        )
    
    def filter_tags(self, queryset, name, value):
        """Filter by tags"""
        tags = [tag.strip() for tag in value.split(',')]
        return queryset.filter(tags__overlap=tags)