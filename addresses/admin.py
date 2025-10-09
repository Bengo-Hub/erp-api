from django.contrib import admin
from .models import AddressBook, DeliveryRegion, AddressValidation
from django.utils import timezone


@admin.register(AddressBook)
class AddressBookAdmin(admin.ModelAdmin):
    list_display = ['user', 'address_label', 'address_type', 'delivery_type', 'county', 'is_default_shipping', 'is_default_billing', 'is_verified']
    list_filter = ['address_type', 'delivery_type', 'county', 'is_default_shipping', 'is_default_billing', 'is_verified', 'created_at']
    search_fields = ['user__username', 'user__email', 'address_label', 'first_name', 'last_name', 'phone', 'street_name', 'county']
    readonly_fields = ['created_at', 'updated_at', 'verification_date']
    
    fieldsets = (
        ('User Information', {
            'fields': ['user', 'address_label', 'address_type']
        }),
        ('Contact Information', {
            'fields': ['first_name', 'last_name', 'phone', 'email', 'other_phone']
        }),
        ('Address Details', {
            'fields': ['county', 'constituency', 'ward', 'street_name', 'building_name', 'floor_number', 'room_number', 'postal_code', 'country']
        }),
        ('GPS Coordinates', {
            'fields': ['latitude', 'longitude']
        }),
        ('Delivery Options', {
            'fields': ['delivery_type', 'pickup_station']
        }),
        ('Default Settings', {
            'fields': ['is_default_shipping', 'is_default_billing']
        }),
        ('Verification', {
            'fields': ['is_verified', 'verification_date', 'verified_by']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at']
        }),
    )

    actions = ['verify_addresses', 'mark_as_default_shipping', 'mark_as_default_billing']

    def verify_addresses(self, request, queryset):
        updated = 0
        for address in queryset.filter(is_verified=False):
            address.is_verified = True
            address.verification_date = timezone.now()
            address.verified_by = request.user
            address.save()
            updated += 1
        self.message_user(request, f'{updated} addresses verified.')
    verify_addresses.short_description = 'Verify selected addresses'

    def mark_as_default_shipping(self, request, queryset):
        updated = 0
        for address in queryset:
            # Clear other default shipping addresses for this user
            AddressBook.objects.filter(user=address.user, is_default_shipping=True).update(is_default_shipping=False)
            address.is_default_shipping = True
            address.save()
            updated += 1
        self.message_user(request, f'{updated} addresses marked as default shipping.')
    mark_as_default_shipping.short_description = 'Mark as default shipping address'

    def mark_as_default_billing(self, request, queryset):
        updated = 0
        for address in queryset:
            # Clear other default billing addresses for this user
            AddressBook.objects.filter(user=address.user, is_default_billing=True).update(is_default_billing=False)
            address.is_default_billing = True
            address.save()
            updated += 1
        self.message_user(request, f'{updated} addresses marked as default billing.')
    mark_as_default_billing.short_description = 'Mark as default billing address'


@admin.register(DeliveryRegion)
class DeliveryRegionAdmin(admin.ModelAdmin):
    list_display = ['name', 'county', 'delivery_charge', 'free_delivery_threshold', 'estimated_delivery_days', 'is_active']
    list_filter = ['county', 'is_active', 'created_at']
    search_fields = ['name', 'county', 'description']
    
    fieldsets = (
        ('Region Information', {
            'fields': ['name', 'county', 'description']
        }),
        ('Delivery Settings', {
            'fields': ['delivery_charge', 'free_delivery_threshold', 'estimated_delivery_days']
        }),
        ('Coverage', {
            'fields': ['is_active', 'covers_counties']
        }),
    )


@admin.register(AddressValidation)
class AddressValidationAdmin(admin.ModelAdmin):
    list_display = ['address', 'validator', 'status', 'validation_method', 'is_valid', 'validated_at']
    list_filter = ['status', 'validation_method', 'is_valid', 'validated_at']
    search_fields = ['address__address_label', 'validator__username', 'validation_notes']
    readonly_fields = ['validated_at', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Validation Information', {
            'fields': ['address', 'validator']
        }),
        ('Validation Details', {
            'fields': ['status', 'validation_method', 'is_valid', 'confidence_score', 'validation_notes']
        }),
        ('Timestamps', {
            'fields': ['validated_at', 'created_at', 'updated_at']
        }),
    )

    actions = ['validate_addresses', 'invalidate_addresses']

    def validate_addresses(self, request, queryset):
        updated = 0
        for validation in queryset.filter(status='pending'):
            validation.validate(validator=request.user, method='manual')
            updated += 1
        self.message_user(request, f'{updated} addresses validated.')
    validate_addresses.short_description = 'Validate selected addresses'

    def invalidate_addresses(self, request, queryset):
        updated = 0
        for validation in queryset.filter(status='pending'):
            validation.invalidate(validator=request.user)
            updated += 1
        self.message_user(request, f'{updated} addresses invalidated.')
    invalidate_addresses.short_description = 'Invalidate selected addresses'
