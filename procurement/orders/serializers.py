#serializers
from rest_framework import serializers
from .models import PurchaseOrder, PurchaseOrderPayment
from core_orders.serializers import BaseOrderSerializer
from approvals.models import Approval
from approvals.serializers import ApprovalSerializer
from procurement.requisitions.models import ProcurementRequest


class PurchaseOrderSerializer(BaseOrderSerializer):
    """Procurement specific purchase order serializer"""
    supplier_name = serializers.SerializerMethodField()
    requisition_reference = serializers.SerializerMethodField()
    approvals = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
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
            'approved_budget', 'actual_cost', 'approvals', 'total_paid'
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


class PurchaseOrderListSerializer(BaseOrderSerializer):
    """Simplified purchase order serializer for list views"""
    supplier_name = serializers.SerializerMethodField()
    requisition_reference = serializers.SerializerMethodField()

    class Meta(BaseOrderSerializer.Meta):
        model = PurchaseOrder
        fields = [
            'id', 'order_number', 'requisition_reference', 'supplier',
            'supplier_name', 'status', 'total', 'expected_delivery',
            'approved_budget', 'actual_cost', 'created_at', 'currency'
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


class PurchaseOrderPaymentSerializer(serializers.ModelSerializer):
    """Serializer for PO payments - Finance integration"""
    po_number = serializers.CharField(source='purchase_order.order_number', read_only=True)
    payment_account_name = serializers.CharField(source='payment_account.account_name', read_only=True)
    payment_reference = serializers.CharField(source='payment.reference_number', read_only=True)
    
    class Meta:
        model = PurchaseOrderPayment
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']
