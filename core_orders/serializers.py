from rest_framework import serializers
from .models import BaseOrder, OrderItem, OrderPayment
from django.contrib.auth import get_user_model
from crm.contacts.models import Contact
from finance.payment.models import Payment
from django.db import models

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']


class ContactSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    # Expose user's name/email via helper fields for compatibility
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = [
            'id', 'user', 'business_name', 'designation', 'contact_type',
            'phone', 'alternative_contact', 'business_address',
            'first_name', 'last_name', 'email', 'full_name'
        ]

    def get_first_name(self, obj):
        return obj.user.first_name if obj.user else ''

    def get_last_name(self, obj):
        return obj.user.last_name if obj.user else ''

    def get_email(self, obj):
        return obj.user.email if obj.user else ''

    def get_full_name(self, obj):
        if obj.user:
            return f"{obj.user.first_name} {obj.user.last_name}".strip()
        return obj.business_name or ''


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            'id', 'reference_number', 'amount', 'payment_method', 
            'status', 'transaction_id', 'payment_date', 'mobile_money_provider'
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    product_title = serializers.SerializerMethodField()
    product_type = serializers.SerializerMethodField()
    # Accept tax and discount in incoming payloads for compatibility with frontend
    tax_amount = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, write_only=True)
    discount_amount = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, write_only=True)
    
    class Meta:
        model = OrderItem
        # Align serializer fields with the current OrderItem model
        fields = [
            'id', 'order', 'content_type', 'object_id', 'product_title',
            'product_type', 'name', 'description', 'sku', 'quantity',
            'unit_price', 'total_price', 'tax_amount', 'discount_amount', 'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['total_price', 'created_at', 'updated_at']
    
    def get_product_title(self, obj):
        if obj.content_object:
            return str(obj.content_object)
        return "Unknown Product"
    
    def get_product_type(self, obj):
        if obj.content_type:
            return obj.content_type.model
        return "unknown"


class OrderPaymentSerializer(serializers.ModelSerializer):
    payment = PaymentSerializer(read_only=True)
    payment_details = serializers.SerializerMethodField()
    
    class Meta:
        model = OrderPayment
        fields = [
            'id', 'order', 'payment', 'payment_details', 'created_at'
        ]
    
    def get_payment_details(self, obj):
        if obj.payment:
            return {
                'amount': obj.payment.amount,
                'method': obj.payment.payment_method,
                'status': obj.payment.status,
                'transaction_id': obj.payment.transaction_id,
                'payment_date': obj.payment.payment_date
            }
        return None


class BaseOrderSerializer(serializers.ModelSerializer):
    customer = ContactSerializer(read_only=True)
    supplier = ContactSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    # related names on BaseOrder are 'items' and 'payments' in the model
    order_items = OrderItemSerializer(many=True, read_only=True, source='items')
    order_payments = OrderPaymentSerializer(many=True, read_only=True, source='payments')
    total_items = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    
    class Meta:
        model = BaseOrder
        fields = [
            'id', 'order_number', 'order_type', 'customer', 'supplier', 
            'branch', 'created_by', 'subtotal', 'tax_amount', 'discount_amount', 
            'tax_mode', 'tax_rate',
            'shipping_cost', 'total', 'status', 'payment_status', 
            'fulfillment_status', 'shipping_address', 'billing_address',
            'tracking_number', 'shipping_provider', 'estimated_delivery_date',
            'notes', 'kra_compliance', 'order_items', 'order_payments',
            'total_items', 'status_display', 'created_at', 'updated_at'
        ]
        read_only_fields = ['order_number', 'total', 'created_at', 'updated_at']
    
    def get_total_items(self, obj):
        # Use the model's related name 'items'
        return obj.items.aggregate(
            total=models.Sum('quantity')
        )['total'] or 0
    
    def get_status_display(self, obj):
        return obj.get_status_display()


class BaseOrderListSerializer(serializers.ModelSerializer):
    """Simplified serializer for list views"""
    customer = ContactSerializer(read_only=True)
    supplier = ContactSerializer(read_only=True)
    total_items = serializers.SerializerMethodField()
    
    class Meta:
        model = BaseOrder
        fields = [
            'id', 'order_number', 'order_type', 'customer', 'supplier',
            'branch', 'total', 'status', 'payment_status', 'fulfillment_status',
            'total_items', 'created_at'
        ]
    
    def get_total_items(self, obj):
        return obj.items.aggregate(
            total=models.Sum('quantity')
        )['total'] or 0
