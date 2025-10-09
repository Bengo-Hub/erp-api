from rest_framework import serializers
from .models import Contract, ContractOrderLink
from core.validators import validate_date_range, validate_non_negative_decimal


class ContractSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        validate_date_range(attrs.get('start_date'), attrs.get('end_date'))
        value = attrs.get('value')
        if value is not None:
            validate_non_negative_decimal(value, 'value')
        return attrs
    class Meta:
        model = Contract
        fields = ['id', 'supplier', 'title', 'start_date', 'end_date', 'value', 'status', 'terms', 'created_at']


class ContractOrderLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContractOrderLink
        fields = ['id', 'contract', 'purchase_order']
