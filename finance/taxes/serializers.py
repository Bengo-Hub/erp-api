from rest_framework import serializers
from .models import TaxCategory, Tax, TaxGroup, TaxGroupItem, TaxPeriod

class TaxCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxCategory
        fields = '__all__'

class TaxSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source='category.name')
    business_name = serializers.ReadOnlyField(source='business.name')
    
    class Meta:
        model = Tax
        fields = '__all__'

class TaxGroupItemSerializer(serializers.ModelSerializer):
    tax_name = serializers.ReadOnlyField(source='tax.name')
    tax_rate = serializers.ReadOnlyField(source='tax.rate')
    tax_calculation_type = serializers.ReadOnlyField(source='tax.calculation_type')
    
    class Meta:
        model = TaxGroupItem
        fields = ['id', 'tax', 'tax_name', 'tax_rate', 'tax_calculation_type', 'order']

class TaxGroupSerializer(serializers.ModelSerializer):
    items = TaxGroupItemSerializer(source='items.all', many=True, read_only=True)
    business_name = serializers.ReadOnlyField(source='business.name')
    
    class Meta:
        model = TaxGroup
        fields = '__all__'

class TaxPeriodSerializer(serializers.ModelSerializer):
    business_name = serializers.ReadOnlyField(source='business.name')
    period_type_display = serializers.ReadOnlyField(source='get_period_type_display')
    status_display = serializers.ReadOnlyField(source='get_status_display')
    
    class Meta:
        model = TaxPeriod
        fields = '__all__'
