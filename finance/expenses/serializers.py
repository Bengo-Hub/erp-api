from rest_framework import serializers
from .models import Expense, ExpenseCategory, ExpensePayment, PaymentAccounts, ExpenseEmailLog
from approvals.utils import get_current_approver_id, get_pending_approvals_for_object


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
    current_approver_id = serializers.SerializerMethodField()
    pending_approvals = serializers.SerializerMethodField()
    created_by_id = serializers.ReadOnlyField(source='created_by.id')

    class Meta:
        model = Expense
        fields = '__all__'

    def get_current_approver_id(self, obj):
        """Get the current approver ID for this expense."""
        return get_current_approver_id(obj)

    def get_pending_approvals(self, obj):
        """Get pending approvals for this expense."""
        return get_pending_approvals_for_object(obj)

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpensePayment
        fields = '__all__'
