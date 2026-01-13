from rest_framework import serializers
from .models import *
from .currency import CURRENCY_DEFINITIONS, CurrencyService, DEFAULT_CURRENCY, PRIORITY_CURRENCIES
# EmailConfigsSerializer moved to centralized notifications app
# Use: from notifications.serializers import EmailConfigurationSerializer


class CurrencySerializer(serializers.Serializer):
    """Serializer for currency information."""
    code = serializers.CharField()
    name = serializers.CharField()
    symbol = serializers.CharField()
    decimal_places = serializers.IntegerField()
    priority = serializers.IntegerField()


class CurrencyListSerializer(serializers.Serializer):
    """Serializer for currency list response."""
    currencies = CurrencySerializer(many=True)
    priority_currencies = CurrencySerializer(many=True)
    default_currency = serializers.CharField()


class ExchangeRateSerializer(serializers.ModelSerializer):
    """Serializer for ExchangeRate model."""
    from_currency_name = serializers.SerializerMethodField()
    to_currency_name = serializers.SerializerMethodField()
    from_currency_symbol = serializers.SerializerMethodField()
    to_currency_symbol = serializers.SerializerMethodField()

    class Meta:
        model = ExchangeRate
        fields = [
            'id', 'from_currency', 'to_currency', 'rate', 'effective_date',
            'source', 'is_active', 'business', 'created_at', 'updated_at',
            'from_currency_name', 'to_currency_name',
            'from_currency_symbol', 'to_currency_symbol'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_from_currency_name(self, obj):
        info = CURRENCY_DEFINITIONS.get(obj.from_currency, {})
        return info.get('name', obj.from_currency)

    def get_to_currency_name(self, obj):
        info = CURRENCY_DEFINITIONS.get(obj.to_currency, {})
        return info.get('name', obj.to_currency)

    def get_from_currency_symbol(self, obj):
        return CurrencyService.get_symbol(obj.from_currency)

    def get_to_currency_symbol(self, obj):
        return CurrencyService.get_symbol(obj.to_currency)


class CurrencyConversionSerializer(serializers.Serializer):
    """Serializer for currency conversion request."""
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    from_currency = serializers.CharField(max_length=3)
    to_currency = serializers.CharField(max_length=3)
    rate = serializers.DecimalField(max_digits=18, decimal_places=6, required=False, allow_null=True)

    def validate_from_currency(self, value):
        if not CurrencyService.is_valid_currency(value):
            raise serializers.ValidationError(f"Invalid currency code: {value}")
        return value.upper()

    def validate_to_currency(self, value):
        if not CurrencyService.is_valid_currency(value):
            raise serializers.ValidationError(f"Invalid currency code: {value}")
        return value.upper()


class CurrencyConversionResultSerializer(serializers.Serializer):
    """Serializer for currency conversion result."""
    original_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    converted_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    from_currency = serializers.CharField()
    to_currency = serializers.CharField()
    rate_used = serializers.DecimalField(max_digits=18, decimal_places=6)
    formatted_original = serializers.CharField()
    formatted_converted = serializers.CharField()


class RegionsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Regions
        fields = '__all__'

class DepartmentsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Departments
        fields = '__all__'

class ProjectsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Projects
        fields = '__all__'

class ProjectCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectCategory
        fields = '__all__'

class BankInstitutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankInstitution
        fields = '__all__'


class RegionalSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegionalSettings
        fields = ['id', 'timezone', 'date_format', 'financial_year_end', 'currency', 
                  'currency_symbol', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']



# ApplicationBrandingSettingsSerializer removed - use business.serializers.BussinessSerializer
# or business.serializers.BrandingSettingsSerializer for branding settings
# Branding is now managed at the business level for multi-tenant support

# Legacy alias for backward compatibility
BanksSerializer = BankInstitutionSerializer

class BankBranchesSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankBranches
        fields = '__all__'

# BannerSerializer moved to centralized campaigns app
# Use: from crm.campaigns.serializers import CampaignSerializer
    


