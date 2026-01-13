from rest_framework import serializers
from .models import TaxCategory, Tax, TaxGroup, TaxGroupItem, TaxPeriod

class TaxCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxCategory
        fields = '__all__'

class TaxSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source='category.name')
    business_name = serializers.ReadOnlyField(source='business.name')
    # Allow category to be set by name (e.g., "vat") or by ID
    category_code = serializers.CharField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Tax
        fields = '__all__'
        extra_kwargs = {
            'category': {'required': False},
            'business': {'required': False},
        }

    def validate(self, attrs):
        request = self.context.get('request')

        # Handle category - can be ID or name/code
        category_code = attrs.pop('category_code', None)
        if category_code and not attrs.get('category'):
            # Try to find category by name (case-insensitive)
            business = attrs.get('business') or self._get_business_from_request(request)
            if business:
                category = TaxCategory.objects.filter(
                    name__iexact=category_code,
                    business=business
                ).first()
                if not category:
                    # Create the category if it doesn't exist
                    category = TaxCategory.objects.create(
                        name=category_code.upper(),
                        business=business,
                        is_active=True
                    )
                attrs['category'] = category

        # Handle business - get from request headers if not provided
        if not attrs.get('business'):
            business = self._get_business_from_request(request)
            if business:
                attrs['business'] = business

        # Ensure category exists (required field)
        if not attrs.get('category'):
            raise serializers.ValidationError({
                'category': 'Category is required. Provide category (ID) or category_code (name).'
            })

        # Ensure business exists (required field)
        if not attrs.get('business'):
            raise serializers.ValidationError({
                'business': 'Business is required. Provide business ID or set X-Business-ID header.'
            })

        return attrs

    def _get_business_from_request(self, request):
        """Extract business from request headers or user context"""
        if not request:
            return None

        from business.models import Bussiness

        # Try X-Business-ID header first
        business_id = request.headers.get('X-Business-ID') or request.META.get('HTTP_X_BUSINESS_ID')
        if business_id:
            return Bussiness.objects.filter(id=business_id).first()

        # Try from user's employee organisation
        user = request.user
        if hasattr(user, 'employee') and hasattr(user.employee, 'organisation'):
            return user.employee.organisation

        # Try from user's owner businesses
        if hasattr(user, 'owner'):
            return Bussiness.objects.filter(owner=user).first()

        return None

class TaxGroupItemSerializer(serializers.ModelSerializer):
    tax_name = serializers.ReadOnlyField(source='tax.name')
    tax_rate = serializers.ReadOnlyField(source='tax.rate')
    tax_calculation_type = serializers.ReadOnlyField(source='tax.calculation_type')
    
    class Meta:
        model = TaxGroupItem
        fields = ['id', 'tax', 'tax_name', 'tax_rate', 'tax_calculation_type', 'order']

class TaxGroupSerializer(serializers.ModelSerializer):
    items = TaxGroupItemSerializer(source='items.all', many=True, read_only=True)
    business_name = serializers.ReadOnlyField(source='business.name')
    
    class Meta:
        model = TaxGroup
        fields = '__all__'

class TaxPeriodSerializer(serializers.ModelSerializer):
    business_name = serializers.ReadOnlyField(source='business.name')
    period_type_display = serializers.ReadOnlyField(source='get_period_type_display')
    status_display = serializers.ReadOnlyField(source='get_status_display')
    
    class Meta:
        model = TaxPeriod
        fields = '__all__'
