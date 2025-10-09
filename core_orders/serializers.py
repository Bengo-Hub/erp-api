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
    
    class Meta:
        model = Contact
        fields = ['id', 'user', 'first_name', 'last_name', 'email', 'phone']


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
    
    class Meta:
        model = OrderItem
        fields = [
            'id', 'order', 'content_type', 'object_id', 'product_title', 
            'product_type', 'quantity', 'unit_price', 'total_price', 
            'tax_amount', 'discount_amount', 'fulfilled_quantity', 
            'is_fulfilled', 'variant_info', 'created_at', 'updated_at'
        ]
        read_only_fields = ['total_price', 'is_fulfilled']
    
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
    order_items = OrderItemSerializer(many=True, read_only=True, source='orderitems')
    order_payments = OrderPaymentSerializer(many=True, read_only=True, source='orderpayments')
    total_items = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    
    class Meta:
        model = BaseOrder
        fields = [
            'id', 'order_number', 'order_type', 'customer', 'supplier', 
            'branch', 'created_by', 'subtotal', 'tax_amount', 'discount_amount', 
            'shipping_cost', 'total', 'status', 'payment_status', 
            'fulfillment_status', 'delivery_address', 'billing_address',
            'tracking_number', 'shipping_provider', 'expected_delivery',
            'notes', 'kra_compliance', 'order_items', 'order_payments',
            'total_items', 'status_display', 'created_at', 'updated_at'
        ]
        read_only_fields = ['order_number', 'total', 'created_at', 'updated_at']
    
    def get_total_items(self, obj):
        return obj.orderitems.aggregate(
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
        return obj.orderitems.aggregate(
            total=models.Sum('quantity')
        )['total'] or 0
