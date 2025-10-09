from rest_framework import serializers
from .models import Order
from core_orders.models import OrderItem, OrderPayment
from core_orders.serializers import BaseOrderSerializer, OrderItemSerializer as BaseOrderItemSerializer, OrderPaymentSerializer as BaseOrderPaymentSerializer
from django.contrib.auth import get_user_model
from crm.contacts.models import Contact
from ecommerce.product.models import Products
from ecommerce.stockinventory.models import StockInventory
from addresses.models import AddressBook
from ecommerce.stockinventory.serializers import StockSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']


class CustomerSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    
    class Meta:
        model = Contact
        fields = ['id', 'user']


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Products
        fields = ['title']


class StockItemsSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    
    class Meta:
        model = StockInventory
        fields = ['product']
        depth = 2


class OrderItemsSerializer(BaseOrderItemSerializer):
    """E-commerce specific order item serializer"""
    stock = StockItemsSerializer(read_only=True, source='content_object')
    
    class Meta(BaseOrderItemSerializer.Meta):
        fields = BaseOrderItemSerializer.Meta.fields + ['stock']


class OrderSerializer(BaseOrderSerializer):
    """E-commerce specific order serializer"""
    customer = CustomerSerializer(required=False)
    orderitems = OrderItemsSerializer(many=True, read_only=True, source='orderitems')
    orderpayments = BaseOrderPaymentSerializer(many=True, read_only=True, source='orderpayments')

    class Meta(BaseOrderSerializer.Meta):
        model = Order
        fields = BaseOrderSerializer.Meta.fields


class OrdersSerializer(serializers.ModelSerializer):
    """Simplified e-commerce order serializer for list views"""
    customer = CustomerSerializer(required=False)

    class Meta:
        model = Order
        fields = '__all__'
        depth = 1


class OrderItemSerializer(BaseOrderItemSerializer):
    """E-commerce specific order item serializer with order details"""
    order = OrdersSerializer(required=False)

    class Meta(BaseOrderItemSerializer.Meta):
        fields = BaseOrderItemSerializer.Meta.fields + ['order']


# Extended serializers for detailed representations
class AddressSerializer(serializers.ModelSerializer):
    """Serializer for shipping and billing addresses"""
    class Meta:
        model = AddressBook
        fields = [
            'id', 'address_name', 'contact_name', 'address_line1', 
            'address_line2', 'city', 'state', 'postal_code', 
            'country', 'phone', 'email', 'is_default'
        ]


class OrderPaymentDetailSerializer(serializers.ModelSerializer):
    """Serializer for order payments with user details"""
    created_by = UserSerializer(read_only=True)
    
    class Meta:
        model = OrderPayment
        fields = [
            'id', 'payment_method', 'amount', 'transaction_id',
            'payment_date', 'is_successful', 'notes', 'created_by'
        ]


class OrderItemDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for order items with full product details"""
    stock = StockSerializer(read_only=True)
    
    class Meta:
        model = OrderItem
        fields = [
            'id', 'stock', 'quantity', 'retail_price', 
            'tax_rate', 'discount_amount', 'notes', 'variant_info'
        ]
        
    def to_representation(self, instance):
        """Customize representation to include calculated fields"""
        representation = super().to_representation(instance)
        representation['total'] = instance.get_total_retail_price()
        return representation


class OrderDetailSerializer(serializers.ModelSerializer):
    """Comprehensive order serializer with all related details"""
    customer = CustomerSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    shipping_address = AddressSerializer(read_only=True)
    billing_address = AddressSerializer(read_only=True)
    orderitems = OrderItemDetailSerializer(many=True, read_only=True)
    payments = OrderPaymentDetailSerializer(many=True, read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_id', 'reference_id', 'customer', 'created_by',
            'source', 'created_at', 'subtotal', 'tax_amount', 'discount_amount', 
            'shipping_cost', 'order_amount', 'amount_paid', 'balance_due',
            'status', 'payment_status', 'fulfillment_status',
            'shipping_address', 'billing_address', 'tracking_number', 
            'shipping_provider', 'inventory_reserved', 'inventory_allocated',
            'notes', 'orderitems', 'payments'
        ]
        
    def to_representation(self, instance):
        """Customize representation to include derived fields"""
        representation = super().to_representation(instance)
        
        # Calculate total items
        representation['total_items'] = instance.get_total_quantity()
        
        # Format status for display
        representation['status_display'] = instance.get_status_display()
        representation['payment_status_display'] = instance.get_payment_status_display()
        
        # Determine if cancellable
        representation['can_cancel'] = instance.status in ['pending', 'confirmed']
        
        return representation



