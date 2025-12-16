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
        fields = ('image',)

class StockProductSerializer(serializers.ModelSerializer):
    """A compact product representation used when returning stock inventory
    rows. Keeps payloads small for autocomplete and listing endpoints."""
    class Meta:
        model = Products
        fields = ('id', 'title', 'sku', 'serial', 'product_type', 'default_price', 'category', 'brand')


class ProductsSerializer(serializers.ModelSerializer):
    date_updated = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')
    images = ImagesSerializer(many=True)
    # expose branch_ids via related stock entries for drill-down
    branch_ids = serializers.SerializerMethodField()
    # Use a minimal business serializer to avoid large nested payloads when
    # products are embedded inside inventory responses.
    business = BussinessMinimalSerializer(read_only=True)

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

class ProductWriteSerializer(serializers.ModelSerializer):    
    class Meta:
        model = Products
        fields = '__all__'
        extra_kwargs = {
            'category': {'required': False},
            'brand': {'required': False},
            'model': {'required': False},
        }

class CategoriesSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    def get_children(self, obj):
        return CategoriesSerializer(obj.children.all(), many=True).data

    class Meta:
        model = Category
        fields = ('id', 'name', 'display_image', 'children', 'status', 'level', 'order')

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