from rest_framework import serializers
from .models import ProductImages, Products, Category, ProductBrands, ProductModels
from business.models import PickupStations
from business.serializers import BussinessSerializer, BussinessMinimalSerializer
from addresses.models import DeliveryRegion
from .delivery import DeliveryPolicy, RegionalDeliveryPolicy, ProductDeliveryInfo
from django.contrib.auth import get_user_model

User = get_user_model()
# Serializers define the API representation.

class ImagesSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImages
        fields = ('id', 'image')

class StockProductSerializer(serializers.ModelSerializer):
    """A compact product representation used when returning stock inventory
    rows. Keeps payloads small for autocomplete and listing endpoints."""
    class Meta:
        model = Products
        fields = ('id', 'title', 'sku', 'serial', 'product_type', 'default_price', 'category', 'brand')


class StockInfoSerializer(serializers.Serializer):
    """Serializer for stock information to be embedded in product response"""
    id = serializers.IntegerField(read_only=True)
    stock_level = serializers.IntegerField()
    buying_price = serializers.DecimalField(max_digits=14, decimal_places=4)
    selling_price = serializers.DecimalField(max_digits=14, decimal_places=4)
    reorder_level = serializers.IntegerField()
    availability = serializers.CharField()
    branch_id = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()

    def get_branch_id(self, obj):
        return obj.branch.id if obj.branch else None

    def get_branch_name(self, obj):
        return obj.branch.name if obj.branch else None


class ProductsSerializer(serializers.ModelSerializer):
    date_updated = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')
    images = ImagesSerializer(many=True)
    # expose branch_ids via related stock entries for drill-down
    branch_ids = serializers.SerializerMethodField()
    # Use a minimal business serializer to avoid large nested payloads when
    # products are embedded inside inventory responses.
    business = BussinessMinimalSerializer(read_only=True)
    # Stock information for edit mode
    stock = serializers.SerializerMethodField()
    # Convenience fields for frontend (from first stock entry)
    stock_level = serializers.SerializerMethodField()
    buying_price = serializers.SerializerMethodField()
    selling_price = serializers.SerializerMethodField()
    reorder_level = serializers.SerializerMethodField()

    class Meta:
        model = Products
        fields = '__all__'
        # Use explicit nested serializers instead of automatic depth expansion
        # to avoid inadvertently serializing TimeZone/ZoneInfo objects directly.
        depth = 0

    def get_branch_ids(self, obj):
        try:
            # collect distinct branch ids from stock inventory entries
            return list(obj.stock.values_list('branch_id', flat=True).distinct())
        except Exception:
            return []

    def get_stock(self, obj):
        """Return all stock entries for this product"""
        try:
            stocks = obj.stock.all()
            return StockInfoSerializer(stocks, many=True).data
        except Exception:
            return []

    def get_stock_level(self, obj):
        """Return stock level from first stock entry (for convenience)"""
        try:
            first_stock = obj.stock.first()
            return first_stock.stock_level if first_stock else None
        except Exception:
            return None

    def get_buying_price(self, obj):
        """Return buying price from first stock entry (for convenience)"""
        try:
            first_stock = obj.stock.first()
            return float(first_stock.buying_price) if first_stock else None
        except Exception:
            return None

    def get_selling_price(self, obj):
        """Return selling price from first stock entry (for convenience)"""
        try:
            first_stock = obj.stock.first()
            return float(first_stock.selling_price) if first_stock else None
        except Exception:
            return None

    def get_reorder_level(self, obj):
        """Return reorder level from first stock entry (for convenience)"""
        try:
            first_stock = obj.stock.first()
            return first_stock.reorder_level if first_stock else None
        except Exception:
            return None

class ProductWriteSerializer(serializers.ModelSerializer):    
    class Meta:
        model = Products
        fields = '__all__'
        extra_kwargs = {
            'category': {'required': False},
            'brand': {'required': False},
            'model': {'required': False},
        }

class CategoryWriteSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating categories with parent field support"""
    class Meta:
        model = Category
        fields = ('id', 'name', 'parent', 'display_image', 'status', 'order')
        extra_kwargs = {
            'parent': {'required': False, 'allow_null': True},
            'display_image': {'required': False},
            'order': {'required': False},
        }


class CategoriesSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()
    parent_name = serializers.CharField(source='parent.name', read_only=True, allow_null=True)

    def get_children(self, obj):
        return CategoriesSerializer(obj.children.all(), many=True).data

    class Meta:
        model = Category
        fields = ('id', 'name', 'parent', 'parent_name', 'display_image', 'children', 'status', 'level', 'order')

class MainCategoriesSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()
    
    def get_children(self, obj):
        return CategoriesSerializer(obj.children.all(), many=True).data
    
    class Meta:
        model = Category
        fields = ('id', 'name', 'display_image', 'children', 'status', 'level', 'order')

#Brands

class BrandsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductBrands
        fields = '__all__'

#Models

class ModelsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductModels
        fields = '__all__'

class DeliveryRegionsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryRegion
        fields = '__all__'
        
class PickupStationsSerializer(serializers.ModelSerializer):
    region_details = DeliveryRegionsSerializer(source='region', read_only=True)
    
    class Meta:
        model = PickupStations
        fields = '__all__'

class DeliveryPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryPolicy
        fields = '__all__'

class RegionalDeliveryPolicySerializer(serializers.ModelSerializer):
    policy_details = DeliveryPolicySerializer(source='policy', read_only=True)
    region_details = DeliveryRegionsSerializer(source='region', read_only=True)
    
    class Meta:
        model = RegionalDeliveryPolicy
        fields = '__all__'

class ProductDeliveryInfoSerializer(serializers.ModelSerializer):
    policy_details = DeliveryPolicySerializer(source='policy', read_only=True)
    
    class Meta:
        model = ProductDeliveryInfo
        fields = '__all__'