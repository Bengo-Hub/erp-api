from rest_framework import serializers
from datetime import datetime

from crm.contacts.models import Contact
from .models import ProcurementRequest, RequestItem
from business.models import Branch, Bussiness
from approvals.models import Approval
from ecommerce.stockinventory.models import StockInventory


class RequestItemWriteSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating request items - accepts stock_item as ID"""
    stock_item = serializers.PrimaryKeyRelatedField(
        queryset=StockInventory.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = RequestItem
        fields = [
            'id', 'item_type', 'stock_item', 'quantity', 'approved_quantity', 'urgent',
            'description', 'specifications', 'estimated_price', 'supplier',
            'service_description', 'expected_deliverables', 'duration',
            'provider', 'start_date', 'end_date'
        ]
        extra_kwargs = {
            'description': {'required': False},
            'service_description': {'required': False}
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


class RequestItemSerializer(serializers.ModelSerializer):
    """Serializer for reading request items - returns stock_item as nested object"""
    stock_item = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = RequestItem
        fields = [
            'id', 'item_type', 'stock_item', 'quantity', 'approved_quantity', 'urgent',
            'description', 'specifications', 'estimated_price', 'supplier',
            'service_description', 'expected_deliverables', 'duration',
            'provider', 'start_date', 'end_date'
        ]

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
        return None

class ApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Approval
        fields = '__all__'

class ProcurementRequestSerializer(serializers.ModelSerializer):
    items = RequestItemSerializer(many=True, read_only=True)
    status = serializers.CharField(read_only=True)
    requester = serializers.SerializerMethodField()
    requester_id = serializers.ReadOnlyField(source='requester.id')
    approvals = ApprovalSerializer(many=True, read_only=True)
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(),
        required=False,
        allow_null=True
    )
    branch_name = serializers.ReadOnlyField(source='branch.name')
    business = serializers.PrimaryKeyRelatedField(
        queryset=Bussiness.objects.all(),
        required=False,
        allow_null=True
    )
    business_name = serializers.ReadOnlyField(source='business.business_name')
    preferred_suppliers = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(),
        many=True,
        required=False
    )
    # Service request fields - passed through to create service-type RequestItem
    service_description = serializers.CharField(write_only=True, required=False, allow_blank=True)
    expected_deliverables = serializers.CharField(write_only=True, required=False, allow_blank=True)
    duration = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = ProcurementRequest
        fields = [
            'id', 'reference_number', 'request_type', 'purpose', 'requester', 'requester_id',
            'required_by_date', 'status', 'notes', 'created_at', 'updated_at', 'items',
            'branch', 'branch_name', 'business', 'business_name',
            'preferred_suppliers', 'approvals', 'priority',
            'service_description', 'expected_deliverables', 'duration'
        ]

    def get_requester(self, obj):
        """Return requester email or username."""
        if obj.requester:
            return obj.requester.email or obj.requester.username
        return None

    def to_internal_value(self, data):
        """Override to handle field name mappings and date format conversion"""
        # Create a mutable copy if necessary
        if hasattr(data, 'copy'):
            data = data.copy()
        else:
            data = dict(data)

        # Handle 'type' -> 'request_type' field mapping from frontend
        if 'type' in data and 'request_type' not in data:
            data['request_type'] = data.pop('type')

        # Handle ISO datetime format for required_by_date
        # Frontend sends "2026-01-15T21:00:00.000Z", model expects "YYYY-MM-DD"
        if 'required_by_date' in data and data['required_by_date']:
            date_value = data['required_by_date']
            if isinstance(date_value, str) and 'T' in date_value:
                try:
                    # Parse ISO datetime and extract date
                    parsed = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
                    data['required_by_date'] = parsed.date().isoformat()
                except (ValueError, AttributeError):
                    pass  # Let DRF handle validation if parsing fails

        items_data = data.pop('items', [])
        ret = super().to_internal_value(data)

        # Validate items using the write serializer
        if items_data:
            items_serializer = RequestItemWriteSerializer(data=items_data, many=True)
            items_serializer.is_valid(raise_exception=True)
            ret['items'] = items_serializer.validated_data

        return ret

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        suppliers_data = validated_data.pop('preferred_suppliers', None)

        # Extract service fields (not part of ProcurementRequest model)
        service_description = validated_data.pop('service_description', None)
        expected_deliverables = validated_data.pop('expected_deliverables', None)
        duration = validated_data.pop('duration', None)

        request = ProcurementRequest.objects.create(**validated_data)

        # For service-type requests without explicit items, auto-create a service RequestItem
        if request.request_type == 'service' and not items_data and service_description:
            RequestItem.objects.create(
                request=request,
                item_type='service',
                service_description=service_description,
                expected_deliverables=expected_deliverables or '',
                duration=duration or '',
                quantity=1
            )

        for item_data in items_data:
            RequestItem.objects.create(request=request, **item_data)

        if suppliers_data is not None:
            request.preferred_suppliers.set(suppliers_data)
        return request

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', [])
        suppliers_data = validated_data.pop('preferred_suppliers', None)

        # Extract service fields (not part of ProcurementRequest model)
        service_description = validated_data.pop('service_description', None)
        expected_deliverables = validated_data.pop('expected_deliverables', None)
        duration = validated_data.pop('duration', None)

        # Update request fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update items
        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                RequestItem.objects.create(request=instance, **item_data)

        # For service-type requests, update or create service item
        if instance.request_type == 'service' and service_description:
            service_item = instance.items.filter(item_type='service').first()
            if service_item:
                service_item.service_description = service_description
                service_item.expected_deliverables = expected_deliverables or ''
                service_item.duration = duration or ''
                service_item.save()
            elif not items_data:
                RequestItem.objects.create(
                    request=instance,
                    item_type='service',
                    service_description=service_description,
                    expected_deliverables=expected_deliverables or '',
                    duration=duration or '',
                    quantity=1
                )

        # Update suppliers if provided
        if suppliers_data is not None:
            instance.preferred_suppliers.set(suppliers_data)

        return instance
