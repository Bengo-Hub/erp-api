from rest_framework import serializers

from .models import ExchangeRateAPISettings


class ExchangeRateAPISettingsSerializer(serializers.ModelSerializer):
    """Serializer for Exchange Rate API settings with masked access key."""
    access_key_preview = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ExchangeRateAPISettings
        fields = [
            'id', 'provider', 'provider_name', 'api_endpoint', 'access_key',
            'source_currency', 'target_currencies', 'fetch_time',
            'last_fetch_at', 'last_fetch_status', 'last_fetch_error',
            'is_active', 'created_at', 'updated_at', 'access_key_preview'
        ]
        extra_kwargs = {
            'access_key': {'write_only': True, 'required': False, 'allow_null': True, 'allow_blank': True},
            'last_fetch_at': {'read_only': True},
            'last_fetch_status': {'read_only': True},
            'last_fetch_error': {'read_only': True},
        }

    def _last4(self, v):
        v = v or ''
        return '••••' + (v[-4:] if len(v) >= 4 else '')

    def get_access_key_preview(self, obj):
        return self._last4(obj.access_key)
