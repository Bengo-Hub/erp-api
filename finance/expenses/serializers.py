from rest_framework import serializers
from .models import Expense, ExpenseCategory, ExpensePayment, PaymentAccounts

class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = '__all__'

class PaymentAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAccounts
        fields = '__all__'

class ExpenseSerializer(serializers.ModelSerializer):
    category_name=serializers.ReadOnlyField(source="category.name")
    class Meta:
        model = Expense
        fields = '__all__'

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpensePayment
        fields = '__all__'
