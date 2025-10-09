from rest_framework import serializers
from .models import Budget, BudgetLine
from core.validators import validate_date_range, validate_non_negative_decimal


class BudgetLineSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        amount = attrs.get('amount')
        if amount is not None:
            validate_non_negative_decimal(amount, 'amount')
        return attrs
    class Meta:
        model = BudgetLine
        fields = ['id', 'budget', 'category', 'name', 'amount', 'notes']


class BudgetSerializer(serializers.ModelSerializer):
    lines = BudgetLineSerializer(many=True, read_only=True)

    class Meta:
        model = Budget
        fields = [
            'id', 'name', 'start_date', 'end_date', 'status',
            'created_by', 'created_at', 'updated_at', 'lines'
        ]

    def validate(self, attrs):
        validate_date_range(attrs.get('start_date'), attrs.get('end_date'))
        return attrs
