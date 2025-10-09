from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import *

User=get_user_model()


class AccountTypesSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountTypes
        fields = '__all__'

class PaymentAccountsSerializer(serializers.ModelSerializer):
    account_type_name = serializers.ReadOnlyField(source='account_type.name')
    
    class Meta:
        model = PaymentAccounts
        fields = '__all__'

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
