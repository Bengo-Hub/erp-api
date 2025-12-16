from rest_framework import serializers
from .models import *
from django.contrib.auth import get_user_model


User = get_user_model()
# Serializers define the API representation.
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model=User
        fields=['id','username','first_name','last_name']

class SupplierSerializer(serializers.ModelSerializer):
    user=UserSerializer()
    class Meta:
        model=Contact
        fields=['id','user']

class PurchasesSerializer(serializers.ModelSerializer):
    branch_id = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Purchase
        fields = '__all__'

    def get_branch_id(self, obj):
        try:
            return obj.branch.id if obj.branch else None
        except Exception:
            return None

class PurchaseStockItemSerializer(serializers.ModelSerializer):
    class Meta:
        model=StockInventory
        fields=['product','variation','product_type']

class PurchaseItemsSerializer(serializers.ModelSerializer):
    purchase = PurchasesSerializer()
    stock=PurchaseStockItemSerializer()
    from ecommerce.product.models import Products as ProductModel
    product = serializers.PrimaryKeyRelatedField(queryset=ProductModel.objects.all(), required=False)

    class Meta:
        model = PurchaseItems
        fields = '__all__'
        depth = 2


class PurchaseItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseItems
        fields = ('id', 'purchase', 'stock_item', 'product', 'qty', 'discount_amount', 'unit_price', 'sub_total')
