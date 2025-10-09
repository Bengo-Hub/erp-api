"""
Serializers for Integration Features
Notification-related serializers moved to centralized notifications app
"""
from rest_framework import serializers
from .models import (
    KRASettings, MpesaSettings, CardPaymentSettings, PayPalSettings, 
    WebhookEndpoint, WebhookEvent
)

class KRASettingsSerializer(serializers.ModelSerializer):
    """Serializer for KRA eTIMS settings. Handles write-only secrets and display-only decrypted previews when allowed."""
    client_id_preview = serializers.SerializerMethodField(read_only=True)
    client_secret_preview = serializers.SerializerMethodField(read_only=True)
    password_preview = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = KRASettings
        fields = [
            'id', 'integration', 'mode', 'base_url', 'kra_pin', 'branch_code',
            'client_id', 'client_secret', 'username', 'password', 'device_serial', 'pos_serial',
            'token_path', 'invoice_path', 'invoice_status_path',
            'client_id_preview', 'client_secret_preview', 'password_preview',
            'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'client_id': {'write_only': True, 'required': False, 'allow_null': True, 'allow_blank': True},
            'client_secret': {'write_only': True, 'required': False, 'allow_null': True, 'allow_blank': True},
            'password': {'write_only': True, 'required': False, 'allow_null': True, 'allow_blank': True},
        }

    def get_client_id_preview(self, obj):
        try:
            val = obj.client_id or ''
            return '••••' + (val[-4:] if val and len(val) >= 4 else '')
        except Exception:
            return None


# EmailConfigSerializer, SMSConfigSerializer, NotificationConfigSerializer moved to centralized notifications app


class MpesaSettingsSerializer(serializers.ModelSerializer):
    consumer_key_preview = serializers.SerializerMethodField(read_only=True)
    consumer_secret_preview = serializers.SerializerMethodField(read_only=True)
    passkey_preview = serializers.SerializerMethodField(read_only=True)
    security_credential_preview = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = MpesaSettings
        fields = [
            'id', 'integration', 'consumer_key', 'consumer_secret', 'passkey', 'security_credential',
            'short_code', 'base_url', 'callback_base_url', 'initiator_name', 'initiator_password',
            'consumer_key_preview', 'consumer_secret_preview', 'passkey_preview', 'security_credential_preview'
        ]
        extra_kwargs = {
            'consumer_key': {'write_only': True, 'required': False},
            'consumer_secret': {'write_only': True, 'required': False},
            'passkey': {'write_only': True, 'required': False},
            'security_credential': {'write_only': True, 'required': False},
            'initiator_password': {'write_only': True, 'required': False},
        }

    def _last4(self, v):
        v = v or ''
        return '••••' + (v[-4:] if len(v) >= 4 else '')

    def get_consumer_key_preview(self, obj):
        return self._last4(obj.consumer_key)

    def get_consumer_secret_preview(self, obj):
        return self._last4(obj.consumer_secret)

    def get_passkey_preview(self, obj):
        return self._last4(obj.passkey)

    def get_security_credential_preview(self, obj):
        return self._last4(obj.security_credential)


class CardPaymentSettingsSerializer(serializers.ModelSerializer):
    api_key_preview = serializers.SerializerMethodField(read_only=True)
    webhook_secret_preview = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CardPaymentSettings
        fields = [
            'id', 'integration', 'provider', 'is_test_mode', 'api_key', 'public_key', 'webhook_secret',
            'base_url', 'webhook_url', 'success_url', 'cancel_url', 'default_currency', 'business_name', 'statement_descriptor',
            'api_key_preview', 'webhook_secret_preview'
        ]
        extra_kwargs = {
            'api_key': {'write_only': True, 'required': False},
            'webhook_secret': {'write_only': True, 'required': False},
        }

    def _last4(self, v):
        v = v or ''
        return '••••' + (v[-4:] if len(v) >= 4 else '')

    def get_api_key_preview(self, obj):
        return self._last4(obj.api_key)

    def get_webhook_secret_preview(self, obj):
        return self._last4(obj.webhook_secret)


class PayPalSettingsSerializer(serializers.ModelSerializer):
    client_id_preview = serializers.SerializerMethodField(read_only=True)
    client_secret_preview = serializers.SerializerMethodField(read_only=True)
    webhook_id_preview = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PayPalSettings
        fields = [
            'id', 'integration', 'is_test_mode', 'client_id', 'client_secret', 'webhook_id', 'base_url', 'webhook_url',
            'success_url', 'cancel_url', 'default_currency', 'business_name', 'business_email',
            'client_id_preview', 'client_secret_preview', 'webhook_id_preview'
        ]
        extra_kwargs = {
            'client_id': {'write_only': True, 'required': False},
            'client_secret': {'write_only': True, 'required': False},
            'webhook_id': {'write_only': True, 'required': False},
        }

    def _last4(self, v):
        v = v or ''
        return '••••' + (v[-4:] if len(v) >= 4 else '')

    def get_client_id_preview(self, obj):
        return self._last4(obj.client_id)

    def get_client_secret_preview(self, obj):
        return self._last4(obj.client_secret)

    def get_webhook_id_preview(self, obj):
        return self._last4(obj.webhook_id)


class WebhookEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEndpoint
        fields = ['id', 'name', 'url', 'secret', 'is_active', 'created_at', 'updated_at']
        extra_kwargs = {
            'secret': {'write_only': True, 'required': False, 'allow_null': True, 'allow_blank': True}
        }


class WebhookEventSerializer(serializers.ModelSerializer):
    endpoint = WebhookEndpointSerializer(read_only=True)
    endpoint_id = serializers.PrimaryKeyRelatedField(queryset=WebhookEndpoint.objects.all(), source='endpoint', write_only=True)

    class Meta:
        model = WebhookEvent
        fields = ['id', 'endpoint', 'endpoint_id', 'event_type', 'payload', 'status', 'attempts', 'last_error', 'created_at', 'updated_at']
