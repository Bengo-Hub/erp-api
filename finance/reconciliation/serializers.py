from rest_framework import serializers
from .models import BankStatementLine
from finance.accounts.serializers import PaymentAccountsSerializer


class BankStatementLineSerializer(serializers.ModelSerializer):
    account_details = PaymentAccountsSerializer(source='account', read_only=True)
    bank_name = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    
    class Meta:
        model = BankStatementLine
        fields = [
            'id', 'account', 'account_details', 'statement_date', 'description', 'amount',
            'external_ref', 'matched_transaction', 'matched_payment', 'is_reconciled',
            'created_at', 'bank_name', 'status'
        ]
    
    def get_bank_name(self, obj):
        return obj.account.name if obj.account else 'Unknown Bank'
    
    def get_status(self, obj):
        if obj.is_reconciled:
            return 'reconciled'
        elif obj.matched_transaction or obj.matched_payment:
            return 'pending'
        else:
            return 'unreconciled'


