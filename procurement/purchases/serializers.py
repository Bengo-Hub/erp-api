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
    currency_display = serializers.SerializerMethodField(read_only=True)
    formatted_total = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Purchase
        fields = '__all__'

    def get_branch_id(self, obj):
        try:
            return obj.branch.id if obj.branch else None
        except Exception:
            return None

    def get_currency_display(self, obj):
        """Get human-readable currency name."""
        return obj.get_currency_display() if hasattr(obj, 'get_currency_display') else obj.currency

    def get_formatted_total(self, obj):
        """Get formatted total with currency symbol."""
        from core.currency import format_currency
        return format_currency(obj.grand_total, obj.currency)

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
        # Avoid deep automatic nesting which may serialize timezone objects
        depth = 0


class PurchaseItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseItems
        fields = ('id', 'purchase', 'stock_item', 'product', 'qty', 'discount_amount', 'unit_price', 'sub_total')
