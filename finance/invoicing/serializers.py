from rest_framework import serializers
from .models import Invoice, InvoicePayment, InvoiceEmailLog, CreditNote, DebitNote, DeliveryNote, ProformaInvoice
from core_orders.serializers import BaseOrderSerializer, OrderItemSerializer
from crm.contacts.serializers import ContactSerializer
from approvals.utils import get_current_approver_id, get_pending_approvals_for_object


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
    current_approver_id = serializers.SerializerMethodField()
    pending_approvals = serializers.SerializerMethodField()
    created_by_id = serializers.ReadOnlyField(source='created_by.id')

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
            'current_approver_id', 'pending_approvals', 'created_by_id',
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

    def get_current_approver_id(self, obj):
        """Get the current approver ID for this invoice."""
        return get_current_approver_id(obj)

    def get_pending_approvals(self, obj):
        """Get pending approvals for this invoice."""
        return get_pending_approvals_for_object(obj)


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
    id = serializers.IntegerField(required=False, allow_null=True)
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
            'tax_mode', 'tax_rate',
            'items', 'shipping_address', 'billing_address',
            # Currency support
            'currency', 'exchange_rate',
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

    def update(self, instance, validated_data):
        """Update invoice and handle item deletion/creation"""
        items_data = validated_data.pop('items', [])

        # Update invoice fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Process items - delete removed items, create/update remaining
        from core_orders.utils import process_custom_items
        from core_orders.models import OrderItem
        from django.contrib.contenttypes.models import ContentType
        from ecommerce.product.models import Products as Product
        from decimal import Decimal

        # Get IDs of items in the incoming payload (for existing items being kept)
        incoming_item_ids = set()
        for item in items_data:
            item_id = item.get('id')
            if item_id:
                incoming_item_ids.add(item_id)

        # Delete items that are no longer in the payload
        instance.items.exclude(id__in=incoming_item_ids).delete()

        # Process custom items
        processed_items = process_custom_items(
            items=items_data,
            branch=instance.branch,
            order_type='invoice',
            category_name=None,
            created_by=instance.created_by
        )

        # Create/update order items
        for item_data in processed_items:
            item_id = item_data.pop('id', None)
            item_data.pop('tax_amount', None)
            item_data.pop('discount_amount', None)

            quantity = int(item_data.get('quantity', 1) or 1)
            unit_price = Decimal(str(item_data.get('unit_price', 0) or 0))

            total_price = item_data.get('total') or item_data.get('total_price') or item_data.get('subtotal')
            if total_price is None:
                total_price = unit_price * quantity
            total_price = Decimal(str(total_price))

            order_item_kwargs = {
                'order': instance,
                'name': item_data.get('name') or item_data.get('description') or 'Item',
                'description': item_data.get('description', ''),
                'quantity': quantity,
                'unit_price': unit_price,
                'total_price': total_price,
                'notes': item_data.get('notes', '')
            }

            product_id = item_data.get('product_id') or item_data.get('product')
            if product_id:
                try:
                    product = Product.objects.get(pk=product_id)
                    order_item_kwargs['content_type'] = ContentType.objects.get_for_model(product)
                    order_item_kwargs['object_id'] = product.id
                    if not item_data.get('name'):
                        order_item_kwargs['name'] = product.title
                except Product.DoesNotExist:
                    pass

            if item_id:
                # Update existing item
                OrderItem.objects.filter(id=item_id, order=instance).update(**order_item_kwargs)
            else:
                # Create new item
                OrderItem.objects.create(**order_item_kwargs)

        return instance

    def to_internal_value(self, data):
        """Quantize money-like and tax_rate fields"""
        from decimal import Decimal, ROUND_HALF_UP

        def quantize_val(v):
            try:
                d = Decimal(str(v))
                return str(d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            except Exception:
                return v

        data = data.copy() if isinstance(data, dict) else data

        money_fields = ['subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total']
        for f in money_fields:
            if f in data and data[f] is not None:
                data[f] = quantize_val(data[f])

        if 'tax_rate' in data and data['tax_rate'] is not None:
            data['tax_rate'] = quantize_val(data['tax_rate'])

        return super().to_internal_value(data)


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


class DeliveryNoteSerializer(BaseOrderSerializer):
    """Delivery Note Serializer"""
    invoice_number = serializers.CharField(source='source_invoice.invoice_number', read_only=True, allow_null=True)
    purchase_order_number = serializers.CharField(source='source_purchase_order.order_number', read_only=True, allow_null=True)
    customer_details = ContactSerializer(source='customer', read_only=True)
    supplier_details = ContactSerializer(source='supplier', read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta(BaseOrderSerializer.Meta):
        model = DeliveryNote
        fields = BaseOrderSerializer.Meta.fields + [
            'delivery_note_number', 'delivery_date', 'source_invoice', 'invoice_number',
            'source_purchase_order', 'purchase_order_number',
            'delivery_address', 'driver_name', 'driver_phone', 'vehicle_number',
            'received_by', 'received_at', 'receiver_signature', 'special_instructions',
            'status', 'status_display',
            'customer_details', 'supplier_details', 'items'
        ]
        read_only_fields = ['delivery_note_number', 'order_number']


class DeliveryNoteCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating delivery notes from existing documents"""
    source_invoice_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    source_purchase_order_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    delivery_address = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = DeliveryNote
        fields = [
            'source_invoice_id', 'source_purchase_order_id', 'delivery_address',
            'driver_name', 'driver_phone', 'vehicle_number', 'special_instructions'
        ]

    def create(self, validated_data):
        source_invoice_id = validated_data.pop('source_invoice_id', None)
        source_purchase_order_id = validated_data.pop('source_purchase_order_id', None)
        user = self.context.get('request').user if self.context.get('request') else None

        if source_invoice_id:
            from .models import Invoice
            invoice = Invoice.objects.get(pk=source_invoice_id)
            delivery_note = DeliveryNote.create_from_invoice(
                invoice,
                created_by=user,
                delivery_address=validated_data.get('delivery_address')
            )
        elif source_purchase_order_id:
            from procurement.orders.models import PurchaseOrder
            po = PurchaseOrder.objects.get(pk=source_purchase_order_id)
            delivery_note = DeliveryNote.create_from_purchase_order(
                po,
                created_by=user,
                delivery_address=validated_data.get('delivery_address')
            )
        else:
            # Create standalone delivery note
            delivery_note = DeliveryNote.objects.create(**validated_data)

        # Update additional fields
        for field in ['driver_name', 'driver_phone', 'vehicle_number', 'special_instructions']:
            if field in validated_data:
                setattr(delivery_note, field, validated_data[field])
        delivery_note.save()

        return delivery_note


class ProformaInvoiceSerializer(BaseOrderSerializer):
    """Proforma Invoice Serializer"""
    quotation_number = serializers.CharField(source='source_quotation.quotation_number', read_only=True, allow_null=True)
    converted_invoice_number = serializers.CharField(source='converted_invoice.invoice_number', read_only=True, allow_null=True)
    customer_details = ContactSerializer(source='customer', read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_expired = serializers.SerializerMethodField()
    days_until_expiry = serializers.SerializerMethodField()

    class Meta(BaseOrderSerializer.Meta):
        model = ProformaInvoice
        fields = BaseOrderSerializer.Meta.fields + [
            'proforma_number', 'proforma_date', 'valid_until',
            'source_quotation', 'quotation_number',
            'converted_invoice', 'converted_invoice_number',
            'customer_notes', 'terms_and_conditions',
            'status', 'status_display', 'is_expired', 'days_until_expiry',
            'customer_details', 'items'
        ]
        read_only_fields = ['proforma_number', 'order_number', 'converted_invoice']

    def get_is_expired(self, obj):
        from django.utils import timezone
        if obj.valid_until and obj.valid_until < timezone.now().date() and obj.status not in ['converted', 'cancelled']:
            return True
        return False

    def get_days_until_expiry(self, obj):
        from django.utils import timezone
        if obj.valid_until:
            delta = obj.valid_until - timezone.now().date()
            return delta.days
        return None


class ProformaInvoiceCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating proforma invoices from quotations"""
    source_quotation_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = ProformaInvoice
        fields = [
            'source_quotation_id', 'customer', 'branch', 'valid_until',
            'customer_notes', 'terms_and_conditions',
            'subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total',
            'tax_mode', 'tax_rate'
        ]

    def create(self, validated_data):
        source_quotation_id = validated_data.pop('source_quotation_id', None)
        user = self.context.get('request').user if self.context.get('request') else None

        if source_quotation_id:
            from finance.quotations.models import Quotation
            quotation = Quotation.objects.get(pk=source_quotation_id)
            proforma = ProformaInvoice.create_from_quotation(quotation, created_by=user)
        else:
            # Create standalone proforma
            validated_data['created_by'] = user
            proforma = ProformaInvoice.objects.create(**validated_data)

        return proforma


class CreditNoteCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating credit notes from invoices"""
    source_invoice_id = serializers.IntegerField(required=True, write_only=True)
    reason = serializers.CharField(required=True)

    class Meta:
        model = CreditNote
        fields = ['source_invoice_id', 'reason']

    def create(self, validated_data):
        source_invoice_id = validated_data.pop('source_invoice_id')
        reason = validated_data.pop('reason')
        user = self.context.get('request').user if self.context.get('request') else None

        from .models import Invoice
        invoice = Invoice.objects.get(pk=source_invoice_id)
        credit_note = CreditNote.create_from_invoice(invoice, reason=reason, created_by=user)
        return credit_note


class DebitNoteCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating debit notes from invoices"""
    source_invoice_id = serializers.IntegerField(required=True, write_only=True)
    reason = serializers.CharField(required=True)

    class Meta:
        model = DebitNote
        fields = ['source_invoice_id', 'reason']

    def create(self, validated_data):
        source_invoice_id = validated_data.pop('source_invoice_id')
        reason = validated_data.pop('reason')
        user = self.context.get('request').user if self.context.get('request') else None

        from .models import Invoice
        invoice = Invoice.objects.get(pk=source_invoice_id)
        debit_note = DebitNote.create_from_invoice(invoice, reason=reason, created_by=user)
        return debit_note

