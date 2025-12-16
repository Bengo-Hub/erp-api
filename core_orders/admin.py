from django.contrib import admin
from .models import BaseOrder, OrderItem, OrderPayment


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1
    fields = ['name', 'description', 'sku', 'quantity', 'unit_price', 'total_price', 'notes']
    readonly_fields = ['total_price']


class OrderPaymentInline(admin.TabularInline):
    model = OrderPayment
    extra = 1
    fields = ['payment', 'amount_applied', 'notes']


@admin.register(BaseOrder)
class BaseOrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'order_type', 'customer', 'supplier', 'branch', 'status', 'payment_status', 'total']
    list_filter = ['order_type', 'status', 'payment_status', 'source', 'delivery_type', 'order_date', 'branch__business', 'branch']
    search_fields = ['order_number', 'reference_id', 'customer__name', 'supplier__name', 'branch__name']
    readonly_fields = ['order_number', 'created_at', 'updated_at','order_date']
    inlines = [OrderItemInline, OrderPaymentInline]
    
    fieldsets = (
        ('Order Information', {
            'fields': ['order_number', 'reference_id', 'order_type', 'source', 'delivery_type']
        }),
        ('Parties', {
            'fields': ['customer', 'supplier', 'branch', 'created_by']
        }),
        ('Financial Details', {
            'fields': ['subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total', 'amount_paid', 'balance_due']
        }),
        ('Status', {
            'fields': ['status', 'payment_status', 'fulfillment_status']
        }),
        ('Delivery Information', {
            'fields': ['pickup_station', 'shipping_address', 'billing_address', 'tracking_number', 'shipping_provider', 'estimated_delivery_date', 'actual_delivery_date']
        }),
        ('Terms & Notes', {
            'fields': ['terms', 'notes', 'delivery_notes']
        }),
        ('KRA Compliance', {
            'fields': ['kra_compliance', 'tax_reference']
        }),
        ('Timestamps', {
            'fields': ['order_date', 'confirmed_at', 'processing_at', 'packed_at', 'shipped_at', 'delivered_at', 'cancelled_at']
        }),
    )

    actions = ['confirm_orders', 'process_orders', 'pack_orders', 'ship_orders', 'deliver_orders', 'cancel_orders']

    def confirm_orders(self, request, queryset):
        updated = 0
        for order in queryset.filter(status='pending'):
            order.confirm_order()
            updated += 1
        self.message_user(request, f'{updated} orders confirmed.')
    confirm_orders.short_description = 'Confirm selected orders'

    def process_orders(self, request, queryset):
        updated = 0
        for order in queryset.filter(status='confirmed'):
            order.process_order()
            updated += 1
        self.message_user(request, f'{updated} orders marked as processing.')
    process_orders.short_description = 'Process selected orders'

    def pack_orders(self, request, queryset):
        updated = 0
        for order in queryset.filter(status='processing'):
            order.pack_order()
            updated += 1
        self.message_user(request, f'{updated} orders marked as packed.')
    pack_orders.short_description = 'Pack selected orders'

    def ship_orders(self, request, queryset):
        updated = 0
        for order in queryset.filter(status='packed'):
            order.ship_order()
            updated += 1
        self.message_user(request, f'{updated} orders marked as shipped.')
    ship_orders.short_description = 'Ship selected orders'

    def deliver_orders(self, request, queryset):
        updated = 0
        for order in queryset.filter(status__in=['shipped', 'out_for_delivery']):
            order.deliver_order()
            updated += 1
        self.message_user(request, f'{updated} orders marked as delivered.')
    deliver_orders.short_description = 'Deliver selected orders'

    def cancel_orders(self, request, queryset):
        updated = 0
        for order in queryset.filter(status__in=['pending', 'confirmed', 'processing']):
            order.cancel_order()
            updated += 1
        self.message_user(request, f'{updated} orders cancelled.')
    cancel_orders.short_description = 'Cancel selected orders'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            # Filter by business ownership or employment
            owned_orders = qs.filter(customer__business__owner=request.user)
            employee_orders = qs.filter(customer__business__employees__user=request.user)
            orders = owned_orders | employee_orders
            return orders


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['order', 'name', 'sku', 'quantity', 'unit_price', 'total_price']
    list_filter = ['order__order_type', 'order__status']
    search_fields = ['order__order_number', 'name', 'sku', 'description']
    readonly_fields = ['total_price']


@admin.register(OrderPayment)
class OrderPaymentAdmin(admin.ModelAdmin):
    list_display = ['order', 'payment', 'amount_applied', 'created_at']
    list_filter = ['payment__payment_method', 'payment__status', 'created_at']
    search_fields = ['order__order_number', 'payment__reference_number']
    readonly_fields = ['created_at']
