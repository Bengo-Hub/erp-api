from rest_framework import serializers
from .models import Quotation, QuotationEmailLog
from core_orders.serializers import BaseOrderSerializer, OrderItemSerializer
from crm.contacts.serializers import ContactSerializer


class QuotationSerializer(BaseOrderSerializer):
    """Comprehensive Quotation Serializer"""
    customer_details = ContactSerializer(source='customer', read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    validity_period_display = serializers.CharField(source='get_validity_period_display', read_only=True)
    is_expired = serializers.SerializerMethodField()
    days_until_expiry = serializers.SerializerMethodField()
    can_convert = serializers.SerializerMethodField()
    
    class Meta(BaseOrderSerializer.Meta):
        model = Quotation
        fields = BaseOrderSerializer.Meta.fields + [
            'quotation_number', 'quotation_date', 'valid_until', 'status', 'status_display',
            'validity_period', 'validity_period_display', 'custom_validity_days',
            'sent_at', 'viewed_at', 'accepted_at', 'declined_at',
            'introduction', 'customer_notes', 'terms_and_conditions',
            'is_converted', 'converted_at', 'converted_by',
            'discount_type', 'discount_value',
            'follow_up_date', 'reminder_sent',
            'customer_details', 'items', 'is_expired', 'days_until_expiry', 'can_convert',
        ]
        read_only_fields = ['quotation_number', 'order_number', 'sent_at', 'viewed_at', 
                           'accepted_at', 'declined_at', 'is_converted', 'converted_at', 'converted_by']
    
    def get_is_expired(self, obj):
        from django.utils import timezone
        if obj.valid_until and obj.valid_until < timezone.now().date() and obj.status not in ['accepted', 'declined', 'converted', 'cancelled']:
            return True
        return False
    
    def get_days_until_expiry(self, obj):
        from django.utils import timezone
        if obj.valid_until:
            delta = obj.valid_until - timezone.now().date()
            return delta.days
        return None
    
    def get_can_convert(self, obj):
        """Check if quotation can be converted to invoice"""
        return not obj.is_converted and obj.status not in ['expired', 'cancelled', 'declined']


class QuotationEmailLogSerializer(serializers.ModelSerializer):
    """Quotation Email Log Serializer"""
    quotation_number = serializers.CharField(source='quotation.quotation_number', read_only=True)
    email_type_display = serializers.CharField(source='get_email_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = QuotationEmailLog
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'sent_at']


class QuotationCreateSerializer(serializers.ModelSerializer):
    """Simplified serializer for creating quotations"""
    items = OrderItemSerializer(many=True, write_only=True)
    
    class Meta:
        model = Quotation
        fields = [
            'customer', 'branch', 'quotation_date', 'validity_period', 'custom_validity_days',
            'introduction', 'customer_notes', 'terms_and_conditions',
            'subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total',
            'discount_type', 'discount_value',
            'items', 'shipping_address', 'billing_address',
        ]
    
    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        quotation = Quotation.objects.create(**validated_data)
        
        # Process custom items (auto-create products/assets if needed)
        from core_orders.utils import process_custom_items
        from core_orders.models import OrderItem
        
        processed_items = process_custom_items(
            items=items_data,
            branch=quotation.branch,
            order_type='quotation',
            category_name=None,
            created_by=quotation.created_by
        )
        
        # Create order items
        for item_data in processed_items:
            OrderItem.objects.create(order=quotation, **item_data)
        
        return quotation


class QuotationSendSerializer(serializers.Serializer):
    """Serializer for sending quotation"""
    email_to = serializers.EmailField(required=False, help_text="Customer email (optional)")
    send_copy_to = serializers.ListField(
        child=serializers.EmailField(),
        required=False,
        help_text="Additional emails to CC"
    )
    message = serializers.CharField(required=False, allow_blank=True, help_text="Custom message")


class QuotationConvertSerializer(serializers.Serializer):
    """Serializer for converting quotation to invoice"""
    payment_terms = serializers.ChoiceField(
        choices=['due_on_receipt', 'net_15', 'net_30', 'net_45', 'net_60', 'net_90'],
        default='net_30'
    )
    invoice_date = serializers.DateField(required=False)
    custom_message = serializers.CharField(required=False, allow_blank=True)

