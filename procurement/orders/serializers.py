#serializers
from rest_framework import serializers
from .models import PurchaseOrder
from core_orders.serializers import BaseOrderSerializer
from approvals.models import Approval
from approvals.serializers import ApprovalSerializer

class PurchaseOrderSerializer(BaseOrderSerializer):
    """Procurement specific purchase order serializer"""
    supplier_name = serializers.SerializerMethodField()
    requisition_reference = serializers.CharField(source='requisition.reference_number', read_only=True)
    approvals = serializers.SerializerMethodField()
    
    class Meta(BaseOrderSerializer.Meta):
        model = PurchaseOrder
        fields = BaseOrderSerializer.Meta.fields + [
            'requisition', 'supplier_name', 'requisition_reference', 
            'expected_delivery', 'delivery_instructions', 
            'approved_budget', 'actual_cost', 'approvals'
        ]

    def get_supplier_name(self, obj):
        if obj.supplier and obj.supplier.user:
            return f"{obj.supplier.user.first_name} {obj.supplier.user.last_name}"
        return obj.supplier.name if obj.supplier else "Unknown Supplier"

    def get_approvals(self, obj):
        approvals = obj.approvals.all()
        return ApprovalSerializer(approvals, many=True).data


class PurchaseOrderListSerializer(BaseOrderSerializer):
    """Simplified purchase order serializer for list views"""
    supplier_name = serializers.SerializerMethodField()
    requisition_reference = serializers.CharField(source='requisition.reference_number', read_only=True)
    
    class Meta(BaseOrderSerializer.Meta):
        model = PurchaseOrder
        fields = [
            'id', 'order_number', 'requisition_reference', 'supplier', 
            'supplier_name', 'status', 'total', 'expected_delivery', 
            'approved_budget', 'actual_cost', 'created_at'
        ]
    
    def get_supplier_name(self, obj):
        if obj.supplier and obj.supplier.user:
            return f"{obj.supplier.user.first_name} {obj.supplier.user.last_name}"
        return obj.supplier.name if obj.supplier else "Unknown Supplier"