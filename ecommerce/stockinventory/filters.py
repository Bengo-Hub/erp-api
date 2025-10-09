# # filters.py
# import django_filters
# from .models import StockAdjustment

# class StockAdjustmentFilter(django_filters.FilterSet):
#     location = django_filters.CharFilter(field_name='location__name', lookup_expr='icontains')
#     fromdate = django_filters.DateFilter(field_name='adjusted_at', lookup_expr='gte')
#     todate = django_filters.DateFilter(field_name='adjusted_at', lookup_expr='lte')

#     class Meta:
#         model = StockAdjustment
#         fields = ['location', 'fromdate', 'todate']
