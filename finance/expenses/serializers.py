from rest_framework import serializers
from .models import Expense, ExpenseCategory, ExpensePayment, PaymentAccounts, ExpenseEmailLog

class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = '__all__'

class PaymentAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAccounts
        fields = '__all__'

class ExpenseEmailLogSerializer(serializers.ModelSerializer):
    """Serializer for expense email logs"""
    email_type_display = serializers.CharField(source='get_email_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = ExpenseEmailLog
        fields = [
            'id', 'expense', 'email_type', 'email_type_display', 
            'recipient_email', 'sent_at', 'opened_at', 'clicked_at',
            'status', 'status_display'
        ]
        read_only_fields = ['sent_at', 'opened_at', 'clicked_at']

class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source="category.name")
    email_logs = ExpenseEmailLogSerializer(many=True, read_only=True)
    
    class Meta:
        model = Expense
        fields = '__all__'

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpensePayment
        fields = '__all__'
