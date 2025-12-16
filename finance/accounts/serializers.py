from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models import Sum
from .models import *

User=get_user_model()


class AccountTypesSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountTypes
        fields = '__all__'

class PaymentAccountsSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    last_transaction = serializers.SerializerMethodField()
    transaction_count = serializers.SerializerMethodField()

    class Meta:
        model = PaymentAccounts
        fields = [
            'id', 'name', 'account_number', 'account_type', 'currency',
            'opening_balance', 'status', 'description', 'bank_name', 
            'branch', 'swift_code', 'iban', 'created_at', 'updated_at',
            'balance', 'last_transaction', 'transaction_count'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_balance(self, obj):
        from decimal import Decimal

        credits = obj.transactions.filter(
            transaction_type__in=['income', 'refund']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        debits = obj.transactions.filter(
            transaction_type__in=['expense', 'payment', 'transfer']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        opening_balance = obj.opening_balance or Decimal('0.00')
        return opening_balance + credits - debits

    def get_last_transaction(self, obj):
        last_txn = obj.transactions.order_by('-transaction_date').first()
        return last_txn.transaction_date if last_txn else None

    def get_transaction_count(self, obj):
        return obj.transactions.count()

class TransactionSerializer(serializers.ModelSerializer):
    account_name = serializers.ReadOnlyField(source='account.name')
    created_by_name = serializers.ReadOnlyField(source='created_by.username')
    transaction_type_display = serializers.ReadOnlyField(source='get_transaction_type_display')
    
    class Meta:
        model = Transaction
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']

class VoucherSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    
    class Meta:
        model = Voucher
        fields = '__all__'
        
    def get_items(self, obj):
        return VoucherItemSerializer(obj.items.all(), many=True).data

class VoucherItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = VoucherItem
        fields = '__all__'
