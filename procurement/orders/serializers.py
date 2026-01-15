#serializers
from rest_framework import serializers
from .models import PurchaseOrder, PurchaseOrderPayment
from core_orders.serializers import BaseOrderSerializer
from approvals.models import Approval
from approvals.serializers import ApprovalSerializer
from approvals.utils import get_current_approver_id, get_pending_approvals_for_object
from procurement.requisitions.models import ProcurementRequest


class PurchaseOrderSerializer(BaseOrderSerializer):
    """Procurement specific purchase order serializer"""
    supplier_name = serializers.SerializerMethodField()
    requisition_reference = serializers.SerializerMethodField()
    approvals = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
    current_approver_id = serializers.SerializerMethodField()
    pending_approvals_list = serializers.SerializerMethodField()
    created_by_id = serializers.ReadOnlyField(source='created_by.id')
    # Make requisition optional - queryset set at class level to avoid init issues
    requisition = serializers.PrimaryKeyRelatedField(
        queryset=ProcurementRequest.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta(BaseOrderSerializer.Meta):
        model = PurchaseOrder
        fields = BaseOrderSerializer.Meta.fields + [
            'requisition', 'supplier_name', 'requisition_reference',
            'expected_delivery', 'delivery_instructions',
            'approved_budget', 'actual_cost', 'approvals', 'total_paid',
            'current_approver_id', 'pending_approvals_list', 'created_by_id'
        ]

    def get_supplier_name(self, obj):
        if obj.supplier and obj.supplier.user:
            return f"{obj.supplier.user.first_name} {obj.supplier.user.last_name}"
        return obj.supplier.name if obj.supplier else "Unknown Supplier"

    def get_requisition_reference(self, obj):
        """Get requisition reference number, handling null case"""
        if obj.requisition:
            return obj.requisition.reference_number
        return None

    def get_approvals(self, obj):
        approvals = obj.approvals.all()
        return ApprovalSerializer(approvals, many=True).data

    def get_total_paid(self, obj):
        """Get total amount paid for this PO"""
        from django.db.models import Sum
        total = obj.po_payments.aggregate(Sum('amount'))['amount__sum'] or 0
        return float(total)

    def get_current_approver_id(self, obj):
        """Get the current approver ID for this PO."""
        return get_current_approver_id(obj)

    def get_pending_approvals_list(self, obj):
        """Get pending approvals for this PO."""
        return get_pending_approvals_for_object(obj)


class PurchaseOrderListSerializer(BaseOrderSerializer):
    """Simplified purchase order serializer for list views"""
    supplier_name = serializers.SerializerMethodField()
    requisition_reference = serializers.SerializerMethodField()
    current_approver_id = serializers.SerializerMethodField()
    created_by_id = serializers.ReadOnlyField(source='created_by.id')

    class Meta(BaseOrderSerializer.Meta):
        model = PurchaseOrder
        fields = [
            'id', 'order_number', 'requisition_reference', 'supplier',
            'supplier_name', 'status', 'total', 'expected_delivery',
            'approved_budget', 'actual_cost', 'created_at', 'currency',
            'current_approver_id', 'created_by_id'
        ]

    def get_supplier_name(self, obj):
        if obj.supplier and obj.supplier.user:
            return f"{obj.supplier.user.first_name} {obj.supplier.user.last_name}"
        return obj.supplier.name if obj.supplier else "Unknown Supplier"

    def get_requisition_reference(self, obj):
        """Get requisition reference number, handling null case"""
        if obj.requisition:
            return obj.requisition.reference_number
        return None

    def get_current_approver_id(self, obj):
        """Get the current approver ID for this PO."""
        return get_current_approver_id(obj)


class PurchaseOrderItemCreateSerializer(serializers.Serializer):
    """Write-only serializer for incoming PO line items"""
    id = serializers.IntegerField(required=False, allow_null=True)
    product_id = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.IntegerField(required=False, default=1)
    unit_price = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=0)
    unitPrice = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=0)
    subtotal = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=0)
    total = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=0)


class PurchaseOrderCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating purchase orders with item handling"""
    items = PurchaseOrderItemCreateSerializer(many=True, write_only=True, required=False)
    requisition = serializers.PrimaryKeyRelatedField(
        queryset=ProcurementRequest.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = PurchaseOrder
        fields = [
            'supplier', 'branch', 'requisition', 'expected_delivery', 'delivery_instructions',
            'approved_budget', 'subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total',
            'tax_mode', 'tax_rate', 'items', 'shipping_address', 'billing_address', 'notes',
            'currency', 'exchange_rate', 'status'
        ]

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        po = PurchaseOrder.objects.create(**validated_data)

        # Process items
        from core_orders.models import OrderItem
        from django.contrib.contenttypes.models import ContentType
        from ecommerce.product.models import Products as Product
        from decimal import Decimal

        for item_data in items_data:
            item_data.pop('id', None)
            quantity = int(item_data.get('quantity', 1) or 1)
            unit_price = Decimal(str(item_data.get('unit_price') or item_data.get('unitPrice') or 0))

            total_price = item_data.get('total') or item_data.get('subtotal')
            if total_price is None:
                total_price = unit_price * quantity
            total_price = Decimal(str(total_price))

            order_item_kwargs = {
                'order': po,
                'name': item_data.get('name') or item_data.get('description') or 'Item',
                'description': item_data.get('description', ''),
                'quantity': quantity,
                'unit_price': unit_price,
                'total_price': total_price,
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

            OrderItem.objects.create(**order_item_kwargs)

        return po

    def update(self, instance, validated_data):
        """Update PO and handle item deletion/creation"""
        items_data = validated_data.pop('items', [])

        # Update PO fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Process items - delete removed items, create/update remaining
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

        # Create/update order items
        for item_data in items_data:
            item_id = item_data.pop('id', None)
            quantity = int(item_data.get('quantity', 1) or 1)
            unit_price = Decimal(str(item_data.get('unit_price') or item_data.get('unitPrice') or 0))

            total_price = item_data.get('total') or item_data.get('subtotal')
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


class PurchaseOrderPaymentSerializer(serializers.ModelSerializer):
    """Serializer for PO payments - Finance integration"""
    po_number = serializers.CharField(source='purchase_order.order_number', read_only=True)
    payment_account_name = serializers.CharField(source='payment_account.account_name', read_only=True)
    payment_reference = serializers.CharField(source='payment.reference_number', read_only=True)

    class Meta:
        model = PurchaseOrderPayment
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']
