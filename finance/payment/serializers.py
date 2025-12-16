from rest_framework import serializers
from .models import (
    PaymentMethod, Payment, POSPayment, PaymentTransaction, PaymentRefund,
    BillingDocument, BillingItem, BillingDocumentHistory
)
from ecommerce.order.serializers import OrderSerializer
from crm.contacts.serializers import ContactSerializer

class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ['id', 'name', 'code', 'is_active', 'requires_verification']

class PaymentTransactionSerializer(serializers.ModelSerializer):
    branch_id = serializers.SerializerMethodField(read_only=True)
    branch_details = serializers.SerializerMethodField(read_only=True)
    class Meta:
        model = PaymentTransaction
        fields = ['id', 'transaction_type', 'amount', 'status', 'transaction_id', 
             'transaction_date', 'raw_response', 'branch_id', 'branch_details']

    def get_branch_id(self, obj):
        try:
            return obj.branch.id if obj.branch else None
        except Exception:
            return None

    def get_branch_details(self, obj):
        try:
            if obj.branch:
                return {'id': obj.branch.id, 'name': obj.branch.name, 'code': getattr(obj.branch, 'branch_code', None)}
            return None
        except Exception:
            return None

class PaymentRefundSerializer(serializers.ModelSerializer):
    processed_by_name = serializers.CharField(source='processed_by.get_full_name', read_only=True)

    class Meta:
        model = PaymentRefund
        fields = ['id', 'amount', 'reason', 'refund_date', 'processed_by_name', 
                 'status', 'refund_transaction_id']

class BillingItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingItem
        fields = ['id', 'description', 'quantity', 'unit_price', 'tax_rate', 'tax_amount', 'subtotal', 'total', 'product', 'order_item']
        read_only_fields = ['tax_amount', 'subtotal', 'total']

class BillingDocumentHistorySerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = BillingDocumentHistory
        fields = ['id', 'status', 'status_display', 'message', 'created_at', 'created_by', 'created_by_name']

class BillingDocumentSerializer(serializers.ModelSerializer):
    items = BillingItemSerializer(many=True, required=False)
    payments = serializers.SerializerMethodField()
    history = BillingDocumentHistorySerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    updated_by_name = serializers.CharField(source='updated_by.get_full_name', read_only=True)
    customer_details = ContactSerializer(source='customer', read_only=True)
    related_order_details = OrderSerializer(source='related_order', read_only=True)
    days_overdue = serializers.SerializerMethodField()
    branch_id = serializers.SerializerMethodField(read_only=True)
    branch_details = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = BillingDocument
        fields = [
            'id', 'document_number', 'document_type', 'document_type_display',
            'status', 'status_display', 'business', 'location', 'branch', 'branch_id', 'branch_details', 'customer',
            'customer_details', 'related_order', 'related_order_details', 'account',
            'subtotal', 'tax_amount', 'total', 'amount_paid', 'balance_due',
            'issue_date', 'due_date', 'payment_date', 'days_overdue',
            'created_at', 'updated_at', 'created_by', 'created_by_name',
            'updated_by', 'updated_by_name', 'notes', 'terms',
            'items', 'payments', 'history'
        ]
        read_only_fields = [
            'document_number', 'created_at', 'updated_at', 'created_by',
            'created_by_name', 'updated_by', 'updated_by_name', 'balance_due',
            'status_display', 'document_type_display', 'days_overdue'
        ]

    def get_payments(self, obj):
        payments = Payment.objects.filter(document=obj)
        return PaymentSerializer(payments, many=True).data

    def get_branch_id(self, obj):
        try:
            return obj.branch.id if obj.branch else None
        except Exception:
            return None

    def get_branch_details(self, obj):
        try:
            if obj.branch:
                return {'id': obj.branch.id, 'name': obj.branch.name, 'code': getattr(obj.branch, 'branch_code', None)}
            return None
        except Exception:
            return None

    def get_days_overdue(self, obj):
        from django.utils import timezone
        if obj.due_date and obj.status not in [BillingDocument.PAID, BillingDocument.CANCELLED]:
            today = timezone.now().date()
            if today > obj.due_date:
                return (today - obj.due_date).days
        return 0

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        request = self.context.get('request')
        user = request.user if request else None
        
        if user:
            validated_data['created_by'] = user
            
        document = BillingDocument.objects.create(**validated_data)
        
        for item_data in items_data:
            BillingItem.objects.create(document=document, **item_data)
            
        BillingDocumentHistory.objects.create(
            document=document, status=document.status,
            message=f"Created {document.get_document_type_display()}",
            created_by=user
        )
        return document

class PaymentSerializer(serializers.ModelSerializer):
    payment_method_details = PaymentMethodSerializer(source='payment_method', read_only=True)
    transactions = PaymentTransactionSerializer(many=True, read_only=True)
    refunds = PaymentRefundSerializer(many=True, read_only=True)
    verified_by_name = serializers.CharField(source='verified_by.get_full_name', read_only=True)
    document_details = BillingDocumentSerializer(source='document', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'amount', 'payment_method', 'payment_method_details', 'status',
            'reference_number', 'transaction_id', 'payment_date', 'verified_by',
            'verified_by_name', 'verification_date', 'notes', 'transactions', 'refunds',
            'document', 'document_details'
            , 'branch_id', 'branch_details'
        ]
        read_only_fields = ['reference_number', 'verification_date', 'verified_by']

    # Branch helpers
    def get_branch_id(self, obj):
        try:
            return obj.branch.id if obj.branch else None
        except Exception:
            return None

    def get_branch_details(self, obj):
        try:
            if obj.branch:
                return {'id': obj.branch.id, 'name': obj.branch.name, 'code': getattr(obj.branch, 'branch_code', None)}
            return None
        except Exception:
            return None

class POSPaymentSerializer(PaymentSerializer):
    class Meta(PaymentSerializer.Meta):
        model = POSPayment
        fields = PaymentSerializer.Meta.fields + ['sale', 'change_amount', 'tendered_amount']

class CreatePOSPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = POSPayment
        fields = ['sale', 'amount', 'payment_method', 'tendered_amount', 'notes']

    def create(self, validated_data):
        # Calculate change amount
        tendered_amount = validated_data.get('tendered_amount', 0)
        amount = validated_data.get('amount', 0)
        change_amount = max(0, float(tendered_amount) - float(amount))
        
        # Create payment with calculated change
        sale = validated_data.get('sale')
        branch = None
        try:
            branch = sale.register.branch if sale and sale.register else None
        except Exception:
            branch = None
        payment = POSPayment.objects.create(
            **validated_data,
            change_amount=change_amount,
            branch=branch,
            status='completed'  # POS payments are typically completed immediately
        )
        
        # Create a payment transaction record
        PaymentTransaction.objects.create(
            payment=payment,
            transaction_type='payment',
            amount=amount,
            status='completed',
            transaction_id=payment.reference_number,
            branch=payment.branch
        )
        
        return payment 