from rest_framework import serializers
from .models import (
    Bussiness, BusinessLocation, PickupStations,
    ProductSettings, SaleSettings, PrefixSettings, ServiceTypes, BrandingSettings, Branch,
    DocumentSequence
)
from addresses.models import AddressBook, DeliveryRegion
from addresses.serializers import AddressBookSerializer as CentralizedAddressBookSerializer
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes


class BusinessLocationSerializer(serializers.ModelSerializer):
    state = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()
    
    class Meta:
        model = BusinessLocation
        fields = '__all__'
    
    def get_state(self, obj):
        return str(obj.state) if obj.state else None
    
    def get_country(self, obj):
        return str(obj.country) if obj.country else None

class PickupStationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickupStations
        fields = '__all__'

class DeliveryAddressSerializer(serializers.ModelSerializer):
    pickupstations = PickupStationSerializer(many=True, read_only=True)
    
    class Meta:
        model = DeliveryRegion
        fields = '__all__'
        depth = 1


class PickupStationsSerializer(serializers.ModelSerializer):
    region_name = serializers.SerializerMethodField()
    business_name = serializers.SerializerMethodField()
    # Provide a minimal business representation and ensure timezone is a string
    # to avoid ZoneInfo objects leaking into API responses.
    business = serializers.SerializerMethodField()
    
    class Meta:
        model = PickupStations
        # Avoid automatic depth expansion; prefer explicit nested serializers
        # to ensure timezone objects are converted to strings.
        fields = '__all__'
        depth = 0

    def get_business(self, obj):
        b = getattr(obj, 'business', None)
        if not b:
            return None
        tz = getattr(b, 'timezone', None)
        tz_str = getattr(tz, 'key', None) or getattr(tz, 'zone', None) or str(tz) if tz is not None else None
        return {
            'id': b.id,
            'name': b.name,
            'timezone': tz_str
        }
        
    def get_region_name(self, obj):
        return obj.region.name if obj.region else None
        
    def get_business_name(self, obj):
        return obj.business.name if obj.business else None

class PickupStationMinimalSerializer(serializers.ModelSerializer):
    """A minimal version of the pickup station serializer for embedding in addresses"""
    class Meta:
        model = PickupStations
        fields = ['id', 'pickup_location', 'description', 'open_hours', 'helpline', 'shipping_charge', 'google_pin']


class BussinessMinimalSerializer(serializers.ModelSerializer):
    """A compact business representation for nested serializers used by the frontend.

    Keeps only the fields the frontend needs to render lists and selects and
    ensures timezone is always a string (no ZoneInfo objects).
    """
    timezone = serializers.SerializerMethodField()

    class Meta:
        model = Bussiness
        fields = ('id', 'name', 'timezone')

    def get_timezone(self, obj):
        tz = getattr(obj, 'timezone', None)
        return getattr(tz, 'key', None) or getattr(tz, 'zone', None) or str(tz) if tz is not None else None

# Using centralized AddressBookSerializer from addresses app

class ProductSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSettings
        fields = '__all__'

class SaleSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleSettings
        fields = '__all__'

class PrefixSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrefixSettings
        fields = '__all__'

class ServiceTypesSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceTypes
        fields = '__all__'

class BrandingSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrandingSettings
        exclude = ('business',)


class DocumentSequenceSerializer(serializers.ModelSerializer):
    """Serializer for document sequences - allows editing current_sequence value."""
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    business_name = serializers.CharField(source='business.name', read_only=True)

    class Meta:
        model = DocumentSequence
        fields = ['id', 'business', 'business_name', 'document_type', 'document_type_display',
                  'current_sequence', 'created_at', 'updated_at']
        read_only_fields = ['id', 'business', 'document_type', 'created_at', 'updated_at']

    def validate_current_sequence(self, value):
        """Validate that sequence value is non-negative."""
        if value < 0:
            raise serializers.ValidationError("Sequence value cannot be negative.")
        return value


class BusinessSettingsSerializer(serializers.ModelSerializer):
    """
    Serializer for business settings page - returns all fields needed by frontend forms.
    Does NOT include nested relations like branches, tax_rates, pickup_stations etc.
    Use dedicated endpoints for those resources.
    """
    timezone = serializers.SerializerMethodField()
    # Accept multiple date formats from frontend
    start_date = serializers.DateField(
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', 'iso-8601'],
        required=False
    )
    business_license_expiry = serializers.DateField(
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', 'iso-8601'],
        required=False,
        allow_null=True
    )
    # Location-based fields (read from related models, write handled separately)
    phone = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    website = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()
    # tax_id maps to kra_number for frontend compatibility
    tax_id = serializers.CharField(source='kra_number', required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = Bussiness
        fields = [
            'id',
            'name',
            'start_date',
            'stock_accounting_method',
            'currency',
            'transaction_edit_days',
            'default_profit_margin',
            'timezone',
            'finacial_year_start_month',
            # Contact fields (read-only from branches/location)
            'phone',
            'email',
            'website',
            'address',
            # Registration/compliance fields
            'tax_id',
            'business_registration_number',
            'business_license_number',
            'business_license_expiry',
            'business_type',
            'county',
            'postal_code',
            # Logo fields
            'logo',
            'watermarklogo',
        ]
        read_only_fields = ['phone', 'email', 'website', 'address']

    def get_timezone(self, obj):
        tz = getattr(obj, 'timezone', None)
        if tz is None:
            return None
        if hasattr(tz, 'key') and tz.key:
            return tz.key
        if hasattr(tz, 'zone') and tz.zone:
            return tz.zone
        return str(tz)

    def get_phone(self, obj):
        """Get phone from main branch or first branch."""
        try:
            branch = obj.branches.filter(is_main_branch=True).first() or obj.branches.first()
            return branch.contact_number if branch else None
        except Exception:
            return None

    def get_email(self, obj):
        """Get email from main branch or first branch."""
        try:
            branch = obj.branches.filter(is_main_branch=True).first() or obj.branches.first()
            return branch.email if branch else None
        except Exception:
            return None

    def get_website(self, obj):
        """Get website from location."""
        try:
            return obj.location.website if obj.location else None
        except Exception:
            return None

    def get_address(self, obj):
        """Get formatted address from location."""
        try:
            loc = obj.location
            if not loc:
                return None
            parts = []
            if loc.building_name:
                parts.append(loc.building_name)
            if loc.street_name:
                parts.append(loc.street_name)
            if loc.city:
                parts.append(loc.city)
            if loc.county:
                parts.append(loc.county)
            if loc.postal_code:
                parts.append(f"P.O. Box {loc.postal_code}")
            return ', '.join(parts) if parts else loc.city
        except Exception:
            return None


class BussinessSerializer(serializers.ModelSerializer):
    branches = serializers.SerializerMethodField()
    # tax_rates moved to finance.taxes module - use /api/v1/finance/taxes/rates/
    prefix_settings = PrefixSettingsSerializer(many=True, read_only=True)
    product_settings = ProductSettingsSerializer(many=True, read_only=True)
    sale_settings = SaleSettingsSerializer(many=True, read_only=True)
    service_types = ServiceTypesSerializer(many=True, read_only=True)
    delivery_regions = DeliveryAddressSerializer(many=True, read_only=True)
    pickup_stations = PickupStationsSerializer(many=True, read_only=True)
    address_book = CentralizedAddressBookSerializer(many=True, read_only=True)
    timezone = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()
    branding = BrandingSettingsSerializer(read_only=True)
    branding_settings = serializers.SerializerMethodField()
    
    class Meta:
        model = Bussiness
        fields = '__all__'
    
    def validate_business_stamp(self, value):
        """Validate business stamp file for security."""
        if value:
            try:
                from core.file_security import scan_stamp_file
                result = scan_stamp_file(value, strict=True)
                if not result['is_safe']:
                    raise serializers.ValidationError('; '.join(result['errors']))
            except ImportError:
                # Fallback validation if file_security module not available
                if hasattr(value, 'size') and value.size > 5 * 1024 * 1024:
                    raise serializers.ValidationError('Stamp file too large (max 5MB)')
                if hasattr(value, 'content_type'):
                    valid_types = ['image/png', 'image/jpeg', 'image/webp']
                    if value.content_type not in valid_types:
                        raise serializers.ValidationError('Invalid file type. Use PNG, JPEG, or WebP.')
        return value
        
    def get_branches(self, obj):
        """Get branches for this business"""
        from .models import Branch
        branches = Branch.objects.filter(business=obj, is_active=True)
        return [{
            'id': branch.id,
            'name': branch.name,
            'branch_code': branch.branch_code,
            'location': {
                'id': branch.location.id,
                'city': branch.location.city,
                'county': branch.location.county,
                'state': str(branch.location.state) if branch.location.state else None,
                'country': str(branch.location.country) if branch.location.country else None,
                'zip_code': branch.location.zip_code,
                'postal_code': branch.location.postal_code,
            },
            'is_main_branch': branch.is_main_branch,
            'is_active': branch.is_active,
            'created_at': branch.created_at
        } for branch in branches]

    def get_owner(self, obj):
        try:
            owner = getattr(obj, 'owner', None)
            if not owner:
                return None
            return {
                'id': owner.id,
                'username': getattr(owner, 'username', None),
                'email': getattr(owner, 'email', None)
            }
        except Exception:
            return None

    def get_branding_settings(self, obj):
        try:
            # Use model helper to return branding settings dict if available
            return obj.get_branding_settings() if hasattr(obj, 'get_branding_settings') else None
        except Exception:
            return None
    def get_timezone(self, obj):
        """Return a JSON-serializable timezone representation (string).

        Central helper to coerce TimeZoneField / ZoneInfo objects into their
        standard string key (e.g. 'Africa/Nairobi'). Keeps behaviour stable
        across serializers that need the timezone value.
        """
        try:
            tz = getattr(obj, 'timezone', None)
            if tz is None:
                return None

            # Try common attributes and fall back to str()
            if hasattr(tz, 'key') and tz.key:
                return tz.key
            if hasattr(tz, 'zone') and tz.zone:
                return tz.zone
            # Some implementations (zoneinfo.ZoneInfo) stringify to 'zoneinfo.ZoneInfo("Africa/Nairobi")'
            # but calling str(tz) on modern implementations returns 'Africa/Nairobi'
            return str(tz)
        except Exception:
            # As a last resort, coerce to string
            return str(getattr(obj, 'timezone', ''))
    
class BranchSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    class Meta:
        model = Branch
        fields = '__all__'

    def get_location(self, obj):
        return {
            'id': obj.location.id,
            'city': obj.location.city,
            'county': obj.location.county,
            'state': str(obj.location.state) if obj.location.state else None,
            'country': str(obj.location.country) if obj.location.country else None,
            'zip_code': obj.location.zip_code,
            'postal_code': obj.location.postal_code,
        }
