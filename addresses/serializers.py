from rest_framework import serializers
from .models import AddressBook, DeliveryRegion, AddressValidation
from django.contrib.auth import get_user_model
from crm.contacts.models import Contact

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']


class ContactSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = Contact
        fields = ['id', 'user', 'first_name', 'last_name', 'email', 'phone']


class DeliveryRegionSerializer(serializers.ModelSerializer):
    pickup_stations_count = serializers.SerializerMethodField()
    
    class Meta:
        model = DeliveryRegion
        fields = [
            'id', 'name', 'county', 'constituency', 'ward', 'description',
            'delivery_fee', 'delivery_time_days', 'is_active', 'pickup_stations_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']
    
    def get_pickup_stations_count(self, obj):
        return obj.pickup_stations.count()


class DeliveryRegionListSerializer(serializers.ModelSerializer):
    """Simplified serializer for list views"""
    class Meta:
        model = DeliveryRegion
        fields = [
            'id', 'name', 'county', 'constituency', 'ward', 'delivery_fee',
            'delivery_time_days', 'is_active', 'created_at'
        ]


class AddressValidationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddressValidation
        fields = [
            'id', 'address', 'status', 'validated_at',
            'validation_notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['validated_at', 'created_at', 'updated_at']


class AddressBookSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    # delivery_region is not currently a FK on AddressBook; expose as None for backward compatibility
    delivery_region = serializers.SerializerMethodField(read_only=True)
    # Expose validations as a list (related_name 'validations') and provide latest via helper if needed
    validations = AddressValidationSerializer(many=True, read_only=True)
    full_address = serializers.SerializerMethodField()
    delivery_type_display = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()
    
    class Meta:
        model = AddressBook
        fields = [
            'id', 'user', 'address_type', 'delivery_type',
            'delivery_type_display', 'full_name', 'phone_number', 'email',
            'county', 'constituency', 'ward', 'street_name', 'building_name',
            'postal_code', 'landmark', 'gps_coordinates', 'delivery_region',
            'pickup_station', 'is_default_shipping', 'is_default_billing', 'is_verified',
            'validations', 'full_address', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']
    
    def get_full_address(self, obj):
        """Generate a formatted full address string"""
        parts = []
        if obj.street_address:
            parts.append(obj.street_address)
        if obj.city:
            parts.append(obj.city)
        if obj.ward:
            parts.append(obj.ward)
        if obj.constituency:
            parts.append(obj.constituency)
        if obj.county:
            parts.append(obj.county)
        if obj.postal_code:
            parts.append(obj.postal_code)
        
        return ", ".join(parts) if parts else "Address not specified"
    
    def get_delivery_type_display(self, obj):
        return obj.get_delivery_type_display()

    def get_delivery_region(self, obj):
        # No delivery_region FK exists on AddressBook yet; return None
        return None

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_phone_number(self, obj):
        return obj.phone


class AddressBookListSerializer(serializers.ModelSerializer):
    """Simplified serializer for list views"""
    user = UserSerializer(read_only=True)
    delivery_region = serializers.SerializerMethodField(read_only=True)
    full_address = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()
    
    class Meta:
        model = AddressBook
        fields = [
            'id', 'user', 'address_type', 'delivery_type',
            'full_name', 'phone_number', 'county', 'ward', 'delivery_region',
            'is_default_shipping', 'is_default_billing', 'full_address', 'created_at'
        ]
    
    def get_full_address(self, obj):
        """Generate a formatted full address string"""
        parts = []
        if obj.building_name:
            parts.append(obj.building_name)
        if obj.floor_number:
            parts.append(f"Floor {obj.floor_number}")
        if obj.room_number:
            parts.append(f"Room {obj.room_number}")
        if obj.street_name:
            parts.append(obj.street_name)
        if obj.ward:
            parts.append(obj.ward)
        if obj.constituency:
            parts.append(obj.constituency)
        if obj.county:
            parts.append(obj.county)
        
        return ", ".join(parts) if parts else "Address not specified"

    def get_delivery_region(self, obj):
        return None

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_phone_number(self, obj):
        return obj.phone


class AddressBookCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new addresses"""
    class Meta:
        model = AddressBook
        fields = [
            'user', 'address_label', 'address_type', 'delivery_type',
            'first_name', 'last_name', 'phone', 'other_phone', 'email',
            'county', 'constituency', 'ward', 'street_name', 'building_name',
            'floor_number', 'room_number', 'postal_code', 'country',
            'latitude', 'longitude', 'pickup_station', 'is_default_shipping', 'is_default_billing'
        ]
    
    def validate(self, attrs):
        """Custom validation for address data"""
        # Ensure user is provided
        if not attrs.get('user'):
            raise serializers.ValidationError("User must be provided")
        
        # Validate GPS coordinates if provided
        gps_coordinates = attrs.get('gps_coordinates')
        if gps_coordinates:
            try:
                lat, lng = gps_coordinates.split(',')
                float(lat.strip())
                float(lng.strip())
            except (ValueError, AttributeError):
                raise serializers.ValidationError(
                    "GPS coordinates must be in format 'latitude,longitude'"
                )
        
        # If setting as default, unset other default addresses for the same user
        if attrs.get('is_default'):
            user = attrs.get('user')
            if user:
                AddressBook.objects.filter(user=user, is_default=True).update(is_default=False)
        
        return attrs
