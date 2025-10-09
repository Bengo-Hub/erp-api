from rest_framework import serializers
from .models import CartSession, CartItem, SavedForLater
from .coupons import Coupon, CartCoupon
from ecommerce.stockinventory.models import StockInventory
from django.contrib.auth import get_user_model

User = get_user_model()

class StockInventorySerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source='product.title')
    product_image = serializers.SerializerMethodField()
    product_id = serializers.IntegerField(source='product.id')
    brand = serializers.CharField(source='product.brand.title', allow_null=True)
    category = serializers.CharField(source='product.category.name', allow_null=True)
    variation = serializers.SerializerMethodField()
    
    class Meta:
        model = StockInventory
        fields = ['id', 'product_id', 'product_title', 'product_image', 'brand', 'category',
                 'selling_price', 'discount', 'stock_level', 'availability', 'variation']
    
    def get_product_image(self, obj):
        request = self.context.get('request')
        if obj.product.images.first() and hasattr(obj.product.images.first(), 'url'):
            image_url = obj.product.images.first().url
            if request is not None:
                return request.build_absolute_uri(image_url)
            return image_url
        return None
    
    def get_variation(self, obj):
        return {"title": obj.variation.title if obj.variation else None,
                "id": obj.variation.id if obj.variation else None,
                "sku": obj.variation.sku if obj.variation else None
               }

class CartItemSerializer(serializers.ModelSerializer):
    stock = StockInventorySerializer(source='stock_item', read_only=True)
    stock_item_id = serializers.PrimaryKeyRelatedField(
        source='stock_item', queryset=StockInventory.objects.all(), write_only=True
    )
    
    class Meta:
        model = CartItem
        fields = ['id', 'stock', 'stock_item_id', 'quantity', 'tax_amount', 'discount_amount', 'item_subtotal', 'item_total', 'added_at']
        read_only_fields = ['item_subtotal', 'item_total', 'added_at']
    
    def create(self, validated_data):
        stock_item = validated_data.get('stock_item')
        cart = self.context.get('cart')
        
        if not cart:
            raise serializers.ValidationError("Cart session not provided")
        
        # # Set the selling price from the stock item if not provided
        # if 'selling_price' not in validated_data or validated_data['selling_price'] == 0:
        #     validated_data['selling_price'] = stock_item.selling_price or 0
        
        # Check if item with same stock and variant exists
        existing_item = CartItem.objects.filter(
            cart=cart,
            stock_item=stock_item,
        ).first()
        
        if existing_item:
            # Update quantity instead of creating new
            existing_item.quantity += validated_data.get('quantity', 1)
            existing_item.save()
            return existing_item
        
        # Create new cart item
        validated_data['cart'] = cart
        return super().create(validated_data)

class CouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = ['id', 'code', 'discount_type', 'discount_value', 'minimum_order_amount',
                 'start_date', 'end_date', 'is_active', 'description']
        read_only_fields = ['id', 'created_at', 'current_uses']

class CartCouponSerializer(serializers.ModelSerializer):
    coupon = CouponSerializer(read_only=True)
    
    class Meta:
        model = CartCoupon
        fields = ['id', 'coupon', 'applied_at', 'discount_amount']
        read_only_fields = ['applied_at']

class CartSessionSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total_items = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    total_tax = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    applied_coupon = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    
    class Meta:
        model = CartSession
        fields = ['id', 'session_key', 'user', 'items', 'total_items', 'subtotal', 'total_tax', 
                 'total', 'applied_coupon', 'discount', 'created_at', 'updated_at', 'expires_at', 'is_active']
        read_only_fields = ['session_key', 'created_at', 'updated_at', 'expires_at']
    
    def get_total_items(self, obj):
        return obj.get_total_items()
    
    def get_subtotal(self, obj):
        return obj.get_subtotal()
    
    def get_total_tax(self, obj):
        return obj.get_total_tax()
    
    def get_total(self, obj):
        total = obj.get_total()
        
        # Deduct coupon discount if any
        try:
            cart_coupon = obj.coupon
            if cart_coupon:
                return max(0, total - cart_coupon.discount_amount)
        except CartCoupon.DoesNotExist:
            pass
            
        return total
        
    def get_applied_coupon(self, obj):
        try:
            cart_coupon = obj.coupon
            if cart_coupon:
                return CouponSerializer(cart_coupon.coupon).data
        except CartCoupon.DoesNotExist:
            pass
        return None
        
    def get_discount(self, obj):
        try:
            cart_coupon = obj.coupon
            if cart_coupon:
                return cart_coupon.discount_amount
        except CartCoupon.DoesNotExist:
            pass
        return 0

class SavedForLaterSerializer(serializers.ModelSerializer):
    stock = StockInventorySerializer(source='stock_item', read_only=True)
    stock_item_id = serializers.PrimaryKeyRelatedField(
        source='stock_item', queryset=StockInventory.objects.all(), write_only=True
    )
    
    class Meta:
        model = SavedForLater
        fields = ['id', 'user', 'stock', 'stock_item_id', 'saved_at', 'notes', 'variant_info']
        read_only_fields = ['saved_at']

class CartUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id']
