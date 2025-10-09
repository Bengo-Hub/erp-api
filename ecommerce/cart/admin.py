from django.contrib import admin
from .models import CartSession, CartItem, SavedForLater
from .coupons import Coupon

# Register your models here.
@admin.register(CartSession)
class CartSessionAdmin(admin.ModelAdmin):
    list_display = ['session_key', 'user', 'created_at', 'updated_at', 'expires_at', 'is_active']
    list_filter = ['is_active', 'user']
    search_fields = ['session_key', 'user__username']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ['cart', 'stock_item', 'quantity', 'tax_amount', 'item_subtotal', 'item_total']
    list_filter = ['cart__user', 'stock_item']
    search_fields = ['cart__user__username', 'stock_item__product__title']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business locations where the user is either the owner or an employee
            owned = qs.filter(stock_item__location__business__owner=request.user)
            employees = qs.filter(stock_item__location__business__employees__user=request.user)
            # Combine the two sets of locations using OR operator
            items = owned | employees
            return items

@admin.register(SavedForLater)
class SavedForLaterAdmin(admin.ModelAdmin):
    list_display = ['user', 'stock_item', 'saved_at']
    list_filter = ['user', 'saved_at']
    search_fields = ['user__username', 'stock_item__product__title', 'notes']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ['code', 'discount_type', 'discount_value', 'minimum_order_amount', 'start_date', 'end_date', 'is_active']
    list_filter = ['is_active', 'is_single_use', 'discount_type', 'is_active']
    search_fields = ['code', 'discount_type', 'discount_value', 'minimum_order_amount', 'start_date', 'end_date', 'is_active']
