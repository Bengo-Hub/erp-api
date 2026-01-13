from rest_framework import serializers
from .models import TaxCategory, Tax, TaxGroup, TaxGroupItem, TaxPeriod
from business.models import Bussiness


def get_business_from_request(request):
    """Extract business from request headers or user context.

    Checks headers in this order (case-insensitive):
    1. X-Business-ID / x-business-id header
    2. User's employee organisation
    3. User's owned businesses
    """
    if not request:
        return None

    # Try X-Business-ID header (case-insensitive - Django normalizes to HTTP_X_BUSINESS_ID)
    business_id = (
        request.headers.get('X-Business-ID') or
        request.headers.get('x-business-id') or
        request.META.get('HTTP_X_BUSINESS_ID')
    )
    if business_id:
        return Bussiness.objects.filter(id=business_id).first()

    # Try from user's employee organisation
    user = getattr(request, 'user', None)
    if user and hasattr(user, 'employee') and hasattr(user.employee, 'organisation'):
        return user.employee.organisation

    # Try from user's owner businesses
    if user and hasattr(user, 'owner'):
        return Bussiness.objects.filter(owner=user).first()

    return None


class TaxCategorySerializer(serializers.ModelSerializer):
    """Serializer for TaxCategory with auto business resolution."""
    business = serializers.PrimaryKeyRelatedField(
        queryset=Bussiness.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = TaxCategory
        fields = '__all__'
        validators = []  # Handle unique_together manually

    def validate(self, attrs):
        request = self.context.get('request')

        # Handle business - get from request headers if not provided
        if not attrs.get('business'):
            business = get_business_from_request(request)
            if business:
                attrs['business'] = business

        # Ensure business exists (required field)
        if not attrs.get('business'):
            raise serializers.ValidationError({
                'business': 'Business is required. Provide business ID or set x-business-id header.'
            })

        # Manual unique_together validation (name + business)
        name = attrs.get('name')
        business = attrs.get('business')
        if name and business:
            existing = TaxCategory.objects.filter(name__iexact=name, business=business)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({
                    'name': 'A tax category with this name already exists for this business.'
                })

        return attrs

class FlexibleCategoryField(serializers.Field):
    """Custom field that accepts category as pk (int) or name (string) on write,
    and returns pk on read."""

    def to_representation(self, value):
        """Return the category pk for serialization."""
        if value is None:
            return None
        return value.pk if hasattr(value, 'pk') else value

    def to_internal_value(self, data):
        """Accept both pk (int/numeric string) and name (string)."""
        if data is None or data == '':
            return None
        # Return as-is - we'll resolve in the serializer's validate method
        return data


class TaxSerializer(serializers.ModelSerializer):
    """Serializer for Tax with flexible category input and auto business resolution.

    The category field accepts:
    - Integer pk: Direct category ID reference
    - String name: Category name (case-insensitive) - will auto-create if not found
    """
    category_name = serializers.ReadOnlyField(source='category.name')
    business_name = serializers.ReadOnlyField(source='business.name')
    # Override FK fields to allow flexible input
    category = FlexibleCategoryField(required=False, allow_null=True)
    business = serializers.PrimaryKeyRelatedField(queryset=Bussiness.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Tax
        fields = '__all__'
        # Remove auto-generated UniqueTogetherValidator - we handle it manually in validate()
        validators = []

    def validate(self, attrs):
        request = self.context.get('request')

        # Handle business - get from request headers if not provided
        if not attrs.get('business'):
            business = get_business_from_request(request)
            if business:
                attrs['business'] = business

        # Ensure business exists first (needed for category lookup)
        if not attrs.get('business'):
            raise serializers.ValidationError({
                'business': 'Business is required. Provide business ID or set x-business-id header.'
            })

        business = attrs['business']

        # Handle category - can be pk (int), numeric string, or category name
        category_value = attrs.get('category')

        if category_value is not None:
            # Check if it's a numeric value (pk)
            if isinstance(category_value, int):
                try:
                    attrs['category'] = TaxCategory.objects.get(pk=category_value)
                except TaxCategory.DoesNotExist:
                    raise serializers.ValidationError({
                        'category': f'Tax category with ID {category_value} does not exist.'
                    })
            elif isinstance(category_value, str):
                if category_value.isdigit():
                    # Numeric string - treat as pk
                    try:
                        attrs['category'] = TaxCategory.objects.get(pk=int(category_value))
                    except TaxCategory.DoesNotExist:
                        raise serializers.ValidationError({
                            'category': f'Tax category with ID {category_value} does not exist.'
                        })
                else:
                    # Category name - find or create
                    category = TaxCategory.objects.filter(
                        name__iexact=category_value,
                        business=business
                    ).first()
                    if not category:
                        # Create the category if it doesn't exist
                        category = TaxCategory.objects.create(
                            name=category_value.upper(),
                            business=business,
                            is_active=True
                        )
                    attrs['category'] = category
            elif hasattr(category_value, 'pk'):
                # Already a TaxCategory instance
                pass
            else:
                raise serializers.ValidationError({
                    'category': 'Invalid category value.'
                })

        # Ensure category exists (required field)
        if not attrs.get('category'):
            raise serializers.ValidationError({
                'category': 'Category is required. Provide category ID or category name.'
            })

        # Manual unique_together validation (name + business)
        name = attrs.get('name')
        if name and business:
            existing = Tax.objects.filter(name__iexact=name, business=business)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({
                    'name': 'A tax with this name already exists for this business.'
                })

        return attrs

class TaxGroupItemSerializer(serializers.ModelSerializer):
    tax_name = serializers.ReadOnlyField(source='tax.name')
    tax_rate = serializers.ReadOnlyField(source='tax.rate')
    tax_calculation_type = serializers.ReadOnlyField(source='tax.calculation_type')
    
    class Meta:
        model = TaxGroupItem
        fields = ['id', 'tax', 'tax_name', 'tax_rate', 'tax_calculation_type', 'order']

class TaxGroupSerializer(serializers.ModelSerializer):
    """Serializer for TaxGroup with auto business resolution."""
    items = TaxGroupItemSerializer(source='items.all', many=True, read_only=True)
    business_name = serializers.ReadOnlyField(source='business.name')
    business = serializers.PrimaryKeyRelatedField(
        queryset=Bussiness.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = TaxGroup
        fields = '__all__'
        validators = []

    def validate(self, attrs):
        request = self.context.get('request')

        if not attrs.get('business'):
            business = get_business_from_request(request)
            if business:
                attrs['business'] = business

        if not attrs.get('business'):
            raise serializers.ValidationError({
                'business': 'Business is required. Provide business ID or set x-business-id header.'
            })

        # Manual unique_together validation (name + business)
        name = attrs.get('name')
        business = attrs.get('business')
        if name and business:
            existing = TaxGroup.objects.filter(name__iexact=name, business=business)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({
                    'name': 'A tax group with this name already exists for this business.'
                })

        return attrs


class TaxPeriodSerializer(serializers.ModelSerializer):
    """Serializer for TaxPeriod with auto business resolution."""
    business_name = serializers.ReadOnlyField(source='business.name')
    period_type_display = serializers.ReadOnlyField(source='get_period_type_display')
    status_display = serializers.ReadOnlyField(source='get_status_display')
    business = serializers.PrimaryKeyRelatedField(
        queryset=Bussiness.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = TaxPeriod
        fields = '__all__'

    def validate(self, attrs):
        request = self.context.get('request')

        if not attrs.get('business'):
            business = get_business_from_request(request)
            if business:
                attrs['business'] = business

        if not attrs.get('business'):
            raise serializers.ValidationError({
                'business': 'Business is required. Provide business ID or set x-business-id header.'
            })

        return attrs
