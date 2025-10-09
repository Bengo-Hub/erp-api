from rest_framework import serializers

from crm.contacts.models import Contact
from .models import ProcurementRequest, RequestItem
from business.models import Branch
from approvals.models import Approval

class RequestItemSerializer(serializers.ModelSerializer):
    stock_item = serializers.SerializerMethodField(read_only=True)
    class Meta:
        model = RequestItem
        fields = [
            'id', 'item_type', 'stock_item', 'quantity', 'approved_quantity', 'urgent',
            'description', 'specifications', 'estimated_price', 'supplier',
            'service_description', 'expected_deliverables', 'duration',
            'provider', 'start_date', 'end_date'
        ]
        extra_kwargs = {
            'stock_item': {'required': False},
            'description': {'required': False},
            'service_description': {'required': False}
        }

    def get_stock_item(self, obj):
        if obj.item_type == 'inventory' and obj.stock_item:
            return {
                "id": obj.stock_item.id,
                "product": {
                    "id": obj.stock_item.product.id,
                    "title": obj.stock_item.product.title,
                    "serial": obj.stock_item.product.serial,
                    "sku": obj.stock_item.product.sku,
                },
                "variation": {
                    "id": obj.stock_item.variation.id,
                    "title": obj.stock_item.variation.title,
                    "serial": obj.stock_item.variation.serial,
                    "sku": obj.stock_item.variation.sku,
                } if obj.stock_item.variation else None,
                "branch": obj.stock_item.branch.name,
                "stock_level": obj.stock_item.stock_level,
                "buying_price": obj.stock_item.buying_price,
            }

    def validate(self, data):
        """
        Validate that required fields are present based on item_type
        """
        item_type = data.get('item_type')
        
        if item_type == 'inventory' and not data.get('stock_item'):
            raise serializers.ValidationError("Stock item is required for inventory items")
        elif item_type == 'external' and not data.get('description'):
            raise serializers.ValidationError("Description is required for external items")
        elif item_type == 'service' and not data.get('service_description'):
            raise serializers.ValidationError("Service description is required for services")
            
        return data

class ApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Approval
        fields = '__all__'

class ProcurementRequestSerializer(serializers.ModelSerializer):
    items = RequestItemSerializer(many=True)
    status = serializers.CharField(read_only=True)
    requester = serializers.ReadOnlyField(source='requester.email')
    approvals = ApprovalSerializer(many=True, read_only=True)  # Use the centralized Approval model
    branch = serializers.PrimaryKeyRelatedField(
            queryset=Branch.objects.all(),
        required=False
    )
    preferred_suppliers = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(),
        many=True,
        required=False
    )

    class Meta:
        model = ProcurementRequest
        fields = [
            'id','reference_number', 'request_type', 'purpose', 'requester', 'required_by_date',
            'status', 'notes', 'created_at', 'updated_at', 'items',
            'branch', 'preferred_suppliers', 'approvals'
        ]

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        suppliers_data = validated_data.pop('preferred_suppliers', None)
        
        request = ProcurementRequest.objects.create(**validated_data)
        
        for item_data in items_data:
            RequestItem.objects.create(request=request, **item_data)

        if suppliers_data is not None:
            request.preferred_suppliers.set(suppliers_data)
        return request

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', [])
        suppliers_data = validated_data.pop('preferred_suppliers', None)
        
        # Update request fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update items
        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                RequestItem.objects.create(request=instance, **item_data)
        
        # Update suppliers if provided
        if suppliers_data is not None:
            instance.preferred_suppliers.set(suppliers_data)
            
        return instance
