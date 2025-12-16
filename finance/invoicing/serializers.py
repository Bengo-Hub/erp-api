from rest_framework import serializers
from .models import Invoice, InvoicePayment, InvoiceEmailLog, CreditNote, DebitNote
from core_orders.serializers import BaseOrderSerializer, OrderItemSerializer
from crm.contacts.serializers import ContactSerializer


class InvoiceSerializer(BaseOrderSerializer):
    """Comprehensive Invoice Serializer"""
    customer_details = ContactSerializer(source='customer', read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    balance_due_display = serializers.DecimalField(source='balance_due', read_only=True, max_digits=15, decimal_places=2)
    is_overdue = serializers.SerializerMethodField()
    days_until_due = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    balance_due = serializers.DecimalField(read_only=True, max_digits=15, decimal_places=2)
    payment_terms_display = serializers.CharField(source='get_payment_terms_display', read_only=True)
    
    class Meta(BaseOrderSerializer.Meta):
        model = Invoice
        fields = BaseOrderSerializer.Meta.fields + [
            'invoice_number', 'invoice_date', 'due_date', 'status', 'status_display',
            'payment_terms', 'payment_terms_display', 'custom_terms_days',
            'sent_at', 'viewed_at', 'last_reminder_sent', 'reminder_count',
            'is_scheduled', 'scheduled_send_date',
            'template_name', 'customer_notes', 'terms_and_conditions',
            'source_quotation', 'requires_approval', 'approval_status', 'approved_by', 'approved_at',
            'payment_gateway_enabled', 'payment_gateway_name', 'payment_link',
            'is_recurring', 'recurring_interval', 'next_invoice_date',
            'customer_details', 'items', 'balance_due_display', 'balance_due', 'is_overdue', 'days_until_due',
        ]
        read_only_fields = ['invoice_number', 'order_number', 'sent_at', 'viewed_at', 
                           'approved_by', 'approved_at', 'balance_due']
    
    def get_is_overdue(self, obj):
        from django.utils import timezone
        if obj.due_date and obj.due_date < timezone.now().date() and obj.status not in ['paid', 'cancelled', 'void']:
            return True
        return False
    
    def get_days_until_due(self, obj):
        from django.utils import timezone
        if obj.due_date:
            delta = obj.due_date - timezone.now().date()
            return delta.days
        return None


class InvoiceFrontendSerializer(serializers.ModelSerializer):
    """Compact serializer for frontend invoice detail/list views"""
    customer_details = ContactSerializer(source='customer', read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    balance_due_display = serializers.DecimalField(source='balance_due', read_only=True, max_digits=15, decimal_places=2)
    is_overdue = serializers.SerializerMethodField()
    days_until_due = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    balance_due = serializers.DecimalField(read_only=True, max_digits=15, decimal_places=2)
    payment_terms_display = serializers.CharField(source='get_payment_terms_display', read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'invoice_date', 'due_date', 'status', 'status_display',
            'payment_terms', 'payment_terms_display', 'subtotal', 'tax_amount', 'discount_amount',
            'shipping_cost', 'total', 'balance_due_display', 'balance_due', 'is_overdue', 'days_until_due',
            'customer_notes', 'terms_and_conditions', 'template_name', 'customer_details', 'items'
        ]

    def get_is_overdue(self, obj):
        from django.utils import timezone
        if obj.due_date and obj.due_date < timezone.now().date() and obj.status not in ['paid', 'cancelled', 'void']:
            return True
        return False

    def get_days_until_due(self, obj):
        from django.utils import timezone
        if obj.due_date:
            delta = obj.due_date - timezone.now().date()
            return delta.days
        return None

class InvoiceItemCreateSerializer(serializers.Serializer):
    """Write-only serializer for incoming invoice line items"""
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


class InvoicePaymentSerializer(serializers.ModelSerializer):
    """Invoice Payment Serializer"""
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    payment_account_name = serializers.CharField(source='payment_account.name', read_only=True)
    
    class Meta:
        model = InvoicePayment
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class InvoiceEmailLogSerializer(serializers.ModelSerializer):
    """Invoice Email Log Serializer"""
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    email_type_display = serializers.CharField(source='get_email_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = InvoiceEmailLog
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'sent_at']


class InvoiceCreateSerializer(serializers.ModelSerializer):
    """Simplified serializer for creating invoices"""
    items = InvoiceItemCreateSerializer(many=True, write_only=True)
    
    class Meta:
        model = Invoice
        fields = [
            'customer', 'branch', 'invoice_date', 'payment_terms', 'custom_terms_days',
            'template_name', 'customer_notes', 'terms_and_conditions',
            'subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total',
            'items', 'shipping_address', 'billing_address',
        ]
    
    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        invoice = Invoice.objects.create(**validated_data)
        
        # Process custom items (auto-create products/assets if needed)
        from core_orders.utils import process_custom_items
        from core_orders.models import OrderItem
        from django.contrib.contenttypes.models import ContentType
        from ecommerce.product.models import Products as Product
        from decimal import Decimal
        
        processed_items = process_custom_items(
            items=items_data,
            branch=invoice.branch,
            order_type='invoice',
            category_name=None,
            created_by=invoice.created_by
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
                'order': invoice,
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
        
        return invoice


class InvoiceSendSerializer(serializers.Serializer):
    """Serializer for sending invoice"""
    email_to = serializers.EmailField(required=False, help_text="Customer email (optional, uses customer's email if not provided)")
    send_copy_to = serializers.ListField(
        child=serializers.EmailField(),
        required=False,
        help_text="Additional emails to CC"
    )
    message = serializers.CharField(required=False, allow_blank=True, help_text="Custom message to include")
    schedule_send = serializers.BooleanField(default=False)
    scheduled_date = serializers.DateTimeField(required=False, allow_null=True)


class InvoiceScheduleSerializer(serializers.Serializer):
    """Serializer for scheduling invoice"""
    email_to = serializers.EmailField()
    scheduled_date = serializers.DateTimeField()
    message = serializers.CharField(required=False, allow_blank=True)


class CreditNoteSerializer(BaseOrderSerializer):
    """Credit Note Serializer"""
    invoice_number = serializers.CharField(source='source_invoice.invoice_number', read_only=True)
    customer_details = ContactSerializer(source='customer', read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta(BaseOrderSerializer.Meta):
        model = CreditNote
        fields = BaseOrderSerializer.Meta.fields + [
            'credit_note_number', 'credit_note_date', 'source_invoice', 'invoice_number',
            'status', 'status_display', 'reason',
            'customer_details', 'items'
        ]
        read_only_fields = ['credit_note_number', 'order_number']


class DebitNoteSerializer(BaseOrderSerializer):
    """Debit Note Serializer"""
    invoice_number = serializers.CharField(source='source_invoice.invoice_number', read_only=True)
    customer_details = ContactSerializer(source='customer', read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta(BaseOrderSerializer.Meta):
        model = DebitNote
        fields = BaseOrderSerializer.Meta.fields + [
            'debit_note_number', 'debit_note_date', 'source_invoice', 'invoice_number',
            'status', 'status_display', 'reason',
            'customer_details', 'items'
        ]
        read_only_fields = ['debit_note_number', 'order_number']

