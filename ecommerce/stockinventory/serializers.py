from rest_framework import serializers
from .models import *
from rest_framework import status
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from ecommerce.product.serializers import ProductsSerializer
from authmanagement.serializers import UserSerializer
from business.serializers import BusinessLocationSerializer
from business.models import BusinessLocation
from .models import StockTransaction, StockTransfer, StockTransferItem, StockAdjustment,Favourites
from django.core.exceptions import ValidationError

class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ('user',)
        depth=1

class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = '__all__'

class VariationImagesSerializer(serializers.ModelSerializer):
    class Meta:
        model = VariationImages
        fields = ('image',)



class VariationSerializer(serializers.ModelSerializer):
    images=VariationImagesSerializer(many=True)
    class Meta:
        model = Variations
        fields = ['id', 'title', 'serial', 'sku','images']

class DiscountsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discounts
        fields = '__all__'

class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = '__all__'

class StockSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")
    branch=BranchSerializer()
    product=ProductsSerializer()
    supplier=SupplierSerializer()
    variation = VariationSerializer() 
    total_sales = serializers.SerializerMethodField()

    class Meta:
        model = StockInventory
        fields = '__all__'
        depth=1

    def get_total_sales(self, obj):
        return obj.salesitems.aggregate(total_sales=Sum('qty'))['total_sales'] if obj.salesitems.exists() else 0

class SingleStockSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockInventory
        fields = '__all__'

class FavouritesSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    #stock = serializers.SerializerMethodField()
    
    class Meta:
        model = Favourites
        fields = '__all__'
        depth=1

    def get_user(self, obj):
        user = obj.user
        if user:
            return {
                "id": user.id, 
                "username": user.username, 
                "email": user.email
            }
        return None


class StockTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockTransaction
        fields = '__all__'

class StockTransferItemSerializer(serializers.ModelSerializer):
    stock_item=serializers.SerializerMethodField()
    class Meta:
        model = StockTransferItem
        fields = '__all__'
        read_only_fields = ('sub_total',)
        extra_kwargs = {
            'stock_transfer': {'required': False},
        }
    def get_stock_item(self, obj):
        stock_item = obj.stock_item
        if stock_item:
            return {
                "id": stock_item.id,
                "product": {
                    "id": stock_item.product.id,
                    "title": stock_item.product.title,
                    "serial": stock_item.product.serial,
                    "sku": stock_item.product.sku,
                },
                "variation": {
                    "id": stock_item.variation.id,
                    "title": stock_item.variation.title,
                    "serial": stock_item.variation.serial,
                    "sku": stock_item.variation.sku,
                } if stock_item.variation else None,
                "location": stock_item.location.location_name,
                "stock_level": stock_item.stock_level,
                "buying_price": stock_item.buying_price,
            }
        return None

class StockTransferSerializer(serializers.ModelSerializer):
    transfer_items = StockTransferItemSerializer(many=True)
    added_by_username = serializers.ReadOnlyField(source='added_by.username')
    from_location = serializers.ReadOnlyField(source='location_from.location_name')
    to_location = serializers.ReadOnlyField(source='location_to.location_name')

    class Meta:
        model = StockTransfer
        fields = '__all__'
        read_only_fields = ('ref_no', 'net_total', 'purchase_total', 'added_by', 'transfrer_date')

    def validate(self, data):
        """
        Validate that location_from and location_to are different
        """
        if data.get('location_from') and data.get('location_to'):
            if data['location_from'] == data['location_to']:
                raise serializers.ValidationError(
                    "Cannot transfer to the same location"
                )
        """
        Validate stock item and quantity
        """
        stock_item = data.get('stock_item')
        quantity = data.get('quantity', 0)
        
        if stock_item and quantity > stock_item.stock_level:
            raise serializers.ValidationError(
                f"Not enough stock. Available: {stock_item.stock_level}"
            )
        return data

    def create(self, validated_data):
        transfer_items_data = validated_data.pop('transfer_items', [])
        request = self.context.get('request')
        
        # Set added_by to current user
        if request and hasattr(request, 'user'):
            validated_data['added_by'] = request.user
            validated_data['status'] = 'Pending'
            print(validated_data)

        # Create the transfer
        transfer = StockTransfer.objects.create(**validated_data)
        ## add transfer to every transfer item
        for item_data in transfer_items_data:
            item_data['stock_transfer'] = transfer
        
        # Create transfer items
        for item_data in transfer_items_data:
            # Debugging log for incoming data
            print(f"Processing item_data: {item_data}")

            # Validate required keys
            if not isinstance(item_data, dict):
                raise ValidationError("Each transfer item must be a dictionary.")
            
            # Calculate sub_total based on stock item's buying price
            stock_item = item_data['stock_item']
            quantity = item_data['quantity']
            sub_total = stock_item.buying_price * quantity

            StockTransferItem.objects.get_or_create(
                stock_transfer=transfer,
                stock_item=stock_item,
                quantity=quantity,
                sub_total=sub_total
            )
        ##update status
        transfer.status = request.data.get('status')
        transfer.save()
        return transfer

    def update(self, instance, validated_data):
        transfer_items_data = validated_data.pop('transfer_items', [])
        
        # Update transfer fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Handle transfer items
        if transfer_items_data:
            # Delete existing items if we're replacing them
            instance.transfer_items.all().delete()
            
            # Create new items
            for item_data in transfer_items_data:
                StockTransferItem.objects.create(stock_transfer=instance, **item_data)
        
        instance.save()
        return instance

class StockAdjustmentSerializer(serializers.ModelSerializer):
    added_by_username = serializers.ReadOnlyField(source='adjusted_by.username')
    product_title = serializers.ReadOnlyField(source='stock_item.product.title')
    variation_title = serializers.ReadOnlyField(source='stock_item.variation.title')

    class Meta:
        model = StockAdjustment
        fields = '__all__'

class ReviewsSerializer(serializers.ModelSerializer):
    user = UserSerializer

    class Meta:
        model = Review
        fields = ('text', 'rating', 'user')
        depth = 1

class StockValuationSerializer(serializers.Serializer):
    total_valuation = serializers.DecimalField(max_digits=14, decimal_places=2)
    valuation_by_category = serializers.ListField()

class StockMovementSerializer(serializers.Serializer):
    transaction_date__date = serializers.DateField()
    transaction_type = serializers.CharField()
    total_quantity = serializers.IntegerField()

class StockReconciliationSerializer(serializers.Serializer):
    stock_item = serializers.IntegerField()
    system_count = serializers.IntegerField()
    physical_count = serializers.IntegerField()
    difference = serializers.IntegerField()