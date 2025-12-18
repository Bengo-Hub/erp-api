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
            'tax_mode', 'tax_rate'
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


class QuotationItemCreateSerializer(serializers.Serializer):
    """Write-only serializer for incoming quotation line items"""
    product_id = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.IntegerField(required=False, default=1)
    unit_price = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=0)
    subtotal = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=0)
    total = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=0)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0)
    tax_amount = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=0)
    discount_amount = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=0)


class QuotationCreateSerializer(serializers.ModelSerializer):
    """Simplified serializer for creating quotations"""
    items = QuotationItemCreateSerializer(many=True, write_only=True)

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
        # Attempt to create the quotation; if the DB schema is missing expected
        # columns (e.g., tax_mode/tax_rate on the orders table), raise a
        # meaningful validation error to guide operators to run migrations.
        from django.db import DatabaseError
        try:
            quotation = Quotation.objects.create(**validated_data)
        except DatabaseError as e:
            # Re-raise as a serializer validation error so the API responds with 4xx
            # instead of a 500 Internal Server Error. Include guidance for the fix.
            raise serializers.ValidationError({
                'detail': (
                    'Could not create Quotation due to database schema mismatch: '
                    f'{str(e)}. Please run database migrations (e.g. `python manage.py migrate core_orders`) '
                    'and retry.'
                )
            })

        # Process custom items (auto-create products/assets if needed)
        from core_orders.utils import process_custom_items
        from core_orders.models import OrderItem
        from django.contrib.contenttypes.models import ContentType
        from ecommerce.product.models import Products as Product
        from decimal import Decimal

        processed_items = process_custom_items(
            items=items_data,
            branch=quotation.branch,
            order_type='quotation',
            category_name=None,
            created_by=quotation.created_by
        )

        # Create order items - sanitize and map fields to OrderItem model
        for item_data in processed_items:
            # Remove non-model compatibility fields
            item_data.pop('tax_amount', None)
            item_data.pop('discount_amount', None)

            quantity = int(item_data.get('quantity', 1) or 1)
            unit_price = Decimal(str(item_data.get('unit_price', 0) or 0))

            # Determine total price from payload or compute
            total_price = item_data.get('total') or item_data.get('total_price') or item_data.get('subtotal')
            if total_price is None:
                total_price = unit_price * quantity
            total_price = Decimal(str(total_price))

            # Build fields accepted by OrderItem model
            order_item_kwargs = {
                'order': quotation,
                'name': item_data.get('name') or item_data.get('description') or 'Item',
                'description': item_data.get('description', ''),
                'quantity': quantity,
                'unit_price': unit_price,
                'total_price': total_price,
                'notes': item_data.get('notes', '')
            }

            # If product_id provided, link via GenericForeignKey
            product_id = item_data.get('product_id') or item_data.get('product')
            if product_id:
                try:
                    product = Product.objects.get(pk=product_id)
                    order_item_kwargs['content_type'] = ContentType.objects.get_for_model(product)
                    order_item_kwargs['object_id'] = product.id
                    # Prefer product title if name was not supplied
                    if not item_data.get('name'):
                        order_item_kwargs['name'] = product.title
                except Product.DoesNotExist:
                    # ignore missing product and continue with provided name
                    pass

            OrderItem.objects.create(**order_item_kwargs)

        return quotation

    def to_internal_value(self, data):
        """Coerce money-like fields to 2 decimal places (prevent validation errors from floats with many decimals)."""
        from decimal import Decimal, ROUND_HALF_UP

        def quantize_val(v):
            try:
                d = Decimal(str(v))
                return str(d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            except Exception:
                return v

        data = data.copy() if isinstance(data, dict) else data

        # Top-level monetary fields
        money_fields = ['subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total', 'discount_value']
        for f in money_fields:
            if f in data and data[f] is not None:
                data[f] = quantize_val(data[f])
        # Tax rate: keep as 2-decimal percentage
        if 'tax_rate' in data and data['tax_rate'] is not None:
            data['tax_rate'] = quantize_val(data['tax_rate'])

        # Items: quantize numeric fields inside each item dict before nested validation
        items = data.get('items')
        if isinstance(items, list):
            new_items = []
            for it in items:
                it = it.copy()
                for k in ['unit_price', 'subtotal', 'total', 'tax_amount', 'discount_amount']:
                    if k in it and it[k] is not None:
                        it[k] = quantize_val(it[k])
                new_items.append(it)
            data['items'] = new_items

        return super().to_internal_value(data)


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

