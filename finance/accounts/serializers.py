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
    # Accept flexible inputs for account_type (e.g., 'Bank', 'Bank Account') and normalize
    account_type = serializers.CharField()
    account_type_display = serializers.SerializerMethodField(read_only=True)
    # Allow account_number to be omitted for certain account types (e.g., cash)
    account_number = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = PaymentAccounts
        fields = [
            'id', 'name', 'account_number', 'account_type', 'currency',
            'opening_balance', 'status', 'description', 'bank_name', 
            'branch', 'swift_code', 'iban', 'created_at', 'updated_at',
            'balance', 'last_transaction', 'transaction_count', 'account_type_display'
        ]
        read_only_fields = ['created_at', 'updated_at']
        # account_type_display is computed server-side
        read_only_fields = read_only_fields + ['account_type_display']

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

    def validate_account_type(self, value):
        """Accept case-insensitive or display-name variants for account_type.

        Examples accepted: 'bank', 'Bank', 'Bank Account', 'BANK'
        Normalizes to the choice key used by the model (e.g., 'bank').
        """
        if value is None:
            return value

        # Ensure it's a string
        val = str(value).strip()

        from .models import PaymentAccounts

        # Check exact key match
        for key, display in PaymentAccounts.ACCOUNT_TYPE_CHOICES:
            if val == key:
                return key

        # Case-insensitive key match
        for key, display in PaymentAccounts.ACCOUNT_TYPE_CHOICES:
            if val.lower() == key.lower():
                return key

        # Match against display label (contains)
        for key, display in PaymentAccounts.ACCOUNT_TYPE_CHOICES:
            if val.lower() in display.lower():
                return key

        raise serializers.ValidationError('Invalid account_type')

    def _generate_unique_account_number(self):
        """Generate a short unique account identifier for non-bank accounts when none provided."""
        import uuid
        from .models import PaymentAccounts

        for _ in range(10):
            candidate = f"CASH-{uuid.uuid4().hex[:8].upper()}"
            if not PaymentAccounts.objects.filter(account_number=candidate).exists():
                return candidate
        # Fallback to a UUID if collision persists
        return f"CASH-{uuid.uuid4().hex}"

    def validate(self, attrs):
        # Ensure account_number is provided for non-cash accounts
        acct_type = attrs.get('account_type') or getattr(self.instance, 'account_type', None)
        acct_num = attrs.get('account_number') if 'account_number' in attrs else getattr(self.instance, 'account_number', None)

        if acct_type and acct_type != 'cash' and not acct_num:
            raise serializers.ValidationError({'account_number': 'Account number is required for non-cash accounts.'})

        return super().validate(attrs)

    def get_account_type_display(self, obj):
        # Return the human-readable display for account_type
        try:
            choices = dict(getattr(obj, 'ACCOUNT_TYPE_CHOICES', []))
            return choices.get(getattr(obj, 'account_type'), getattr(obj, 'account_type'))
        except Exception:
            return getattr(obj, 'account_type')

    def create(self, validated_data):
        # If account_number missing for a cash account, generate one
        acct_type = validated_data.get('account_type')
        acct_num = validated_data.get('account_number')
        if (not acct_num) and acct_type == 'cash':
            validated_data['account_number'] = self._generate_unique_account_number()

        return super().create(validated_data)

    def update(self, instance, validated_data):
        # If updating to cash and account_number is being cleared, generate one
        acct_type = validated_data.get('account_type', instance.account_type)
        acct_num = validated_data.get('account_number') if 'account_number' in validated_data else instance.account_number
        if (not acct_num) and acct_type == 'cash':
            validated_data['account_number'] = self._generate_unique_account_number()

        return super().update(instance, validated_data)

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
