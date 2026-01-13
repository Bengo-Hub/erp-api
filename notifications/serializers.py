"""
Serializers for the notifications app
"""
from rest_framework import serializers
from .models import (
    NotificationIntegration, EmailConfiguration, SMSConfiguration,
    PushConfiguration, EmailTemplate, SMSTemplate, PushTemplate,
    EMAIL_PROVIDERS, SMS_PROVIDERS, PUSH_PROVIDERS, INTEGRATION_TYPES
)


class EmailConfigurationSerializer(serializers.ModelSerializer):
    """Serializer for Email Configuration"""
    # Don't expose decrypted passwords in API, use write_only for sensitive fields
    smtp_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True)
    api_secret = serializers.CharField(write_only=True, required=False, allow_blank=True)

    # Read-only fields to indicate if credentials are set
    has_smtp_password = serializers.SerializerMethodField()
    has_api_key = serializers.SerializerMethodField()
    has_api_secret = serializers.SerializerMethodField()

    class Meta:
        model = EmailConfiguration
        fields = [
            'id', 'integration', 'provider', 'from_email', 'from_name',
            'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password',
            'use_tls', 'use_ssl', 'fail_silently', 'timeout',
            'api_key', 'api_secret', 'api_url',
            'has_smtp_password', 'has_api_key', 'has_api_secret',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_has_smtp_password(self, obj):
        return bool(obj.smtp_password)

    def get_has_api_key(self, obj):
        return bool(obj.api_key)

    def get_has_api_secret(self, obj):
        return bool(obj.api_secret)


class SMSConfigurationSerializer(serializers.ModelSerializer):
    """Serializer for SMS Configuration"""
    # Write-only sensitive fields
    account_sid = serializers.CharField(write_only=True, required=False, allow_blank=True)
    auth_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True)
    aws_access_key = serializers.CharField(write_only=True, required=False, allow_blank=True)
    aws_secret_key = serializers.CharField(write_only=True, required=False, allow_blank=True)

    # Read-only indicators
    has_account_sid = serializers.SerializerMethodField()
    has_auth_token = serializers.SerializerMethodField()
    has_api_key = serializers.SerializerMethodField()
    has_aws_credentials = serializers.SerializerMethodField()

    class Meta:
        model = SMSConfiguration
        fields = [
            'id', 'integration', 'provider',
            'account_sid', 'auth_token', 'from_number',
            'api_key', 'api_username',
            'aws_access_key', 'aws_secret_key', 'aws_region',
            'has_account_sid', 'has_auth_token', 'has_api_key', 'has_aws_credentials',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_has_account_sid(self, obj):
        return bool(obj.account_sid)

    def get_has_auth_token(self, obj):
        return bool(obj.auth_token)

    def get_has_api_key(self, obj):
        return bool(obj.api_key)

    def get_has_aws_credentials(self, obj):
        return bool(obj.aws_access_key and obj.aws_secret_key)


class PushConfigurationSerializer(serializers.ModelSerializer):
    """Serializer for Push Configuration"""
    # Write-only sensitive fields
    firebase_server_key = serializers.CharField(write_only=True, required=False, allow_blank=True)
    apns_private_key = serializers.CharField(write_only=True, required=False, allow_blank=True)

    # Read-only indicators
    has_firebase_key = serializers.SerializerMethodField()
    has_apns_credentials = serializers.SerializerMethodField()

    class Meta:
        model = PushConfiguration
        fields = [
            'id', 'integration', 'provider',
            'firebase_server_key', 'firebase_project_id',
            'apns_certificate', 'apns_private_key', 'apns_team_id', 'apns_key_id',
            'has_firebase_key', 'has_apns_credentials',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_has_firebase_key(self, obj):
        return bool(obj.firebase_server_key)

    def get_has_apns_credentials(self, obj):
        return bool(obj.apns_private_key and obj.apns_team_id)


class NotificationIntegrationSerializer(serializers.ModelSerializer):
    """Serializer for Notification Integration with nested config"""
    email_config = EmailConfigurationSerializer(read_only=True)
    sms_config = SMSConfigurationSerializer(read_only=True)
    push_config = PushConfigurationSerializer(read_only=True)
    integration_type_display = serializers.SerializerMethodField()

    class Meta:
        model = NotificationIntegration
        fields = [
            'id', 'name', 'integration_type', 'integration_type_display',
            'provider', 'is_active', 'is_default', 'priority',
            'email_config', 'sms_config', 'push_config',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_integration_type_display(self, obj):
        return dict(INTEGRATION_TYPES).get(obj.integration_type, obj.integration_type)


class NotificationIntegrationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating Notification Integration with config"""
    # Email config fields (optional)
    email_provider = serializers.ChoiceField(choices=EMAIL_PROVIDERS, required=False)
    from_email = serializers.EmailField(required=False)
    from_name = serializers.CharField(required=False, allow_blank=True)
    smtp_host = serializers.CharField(required=False, allow_blank=True)
    smtp_port = serializers.IntegerField(required=False)
    smtp_username = serializers.CharField(required=False, allow_blank=True)
    smtp_password = serializers.CharField(required=False, allow_blank=True)
    use_tls = serializers.BooleanField(required=False)
    use_ssl = serializers.BooleanField(required=False)
    email_api_key = serializers.CharField(required=False, allow_blank=True)
    email_api_secret = serializers.CharField(required=False, allow_blank=True)
    email_api_url = serializers.URLField(required=False, allow_blank=True)

    # SMS config fields (optional)
    sms_provider = serializers.ChoiceField(choices=SMS_PROVIDERS, required=False)
    account_sid = serializers.CharField(required=False, allow_blank=True)
    auth_token = serializers.CharField(required=False, allow_blank=True)
    from_number = serializers.CharField(required=False, allow_blank=True)
    sms_api_key = serializers.CharField(required=False, allow_blank=True)
    api_username = serializers.CharField(required=False, allow_blank=True)
    aws_access_key = serializers.CharField(required=False, allow_blank=True)
    aws_secret_key = serializers.CharField(required=False, allow_blank=True)
    aws_region = serializers.CharField(required=False, allow_blank=True)

    # Push config fields (optional)
    push_provider = serializers.ChoiceField(choices=PUSH_PROVIDERS, required=False)
    firebase_server_key = serializers.CharField(required=False, allow_blank=True)
    firebase_project_id = serializers.CharField(required=False, allow_blank=True)
    apns_certificate = serializers.CharField(required=False, allow_blank=True)
    apns_private_key = serializers.CharField(required=False, allow_blank=True)
    apns_team_id = serializers.CharField(required=False, allow_blank=True)
    apns_key_id = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = NotificationIntegration
        fields = [
            'id', 'name', 'integration_type', 'provider', 'is_active', 'is_default', 'priority',
            # Email fields
            'email_provider', 'from_email', 'from_name', 'smtp_host', 'smtp_port',
            'smtp_username', 'smtp_password', 'use_tls', 'use_ssl',
            'email_api_key', 'email_api_secret', 'email_api_url',
            # SMS fields
            'sms_provider', 'account_sid', 'auth_token', 'from_number',
            'sms_api_key', 'api_username', 'aws_access_key', 'aws_secret_key', 'aws_region',
            # Push fields
            'push_provider', 'firebase_server_key', 'firebase_project_id',
            'apns_certificate', 'apns_private_key', 'apns_team_id', 'apns_key_id'
        ]

    def create(self, validated_data):
        # Extract config data based on integration type
        integration_type = validated_data.get('integration_type')
        config_data = self._extract_config_data(validated_data, integration_type)

        # Create the integration
        integration = NotificationIntegration.objects.create(**validated_data)

        # Create the appropriate config
        self._create_config(integration, integration_type, config_data)

        return integration

    def update(self, instance, validated_data):
        # Extract config data
        config_data = self._extract_config_data(validated_data, instance.integration_type)

        # Update the integration
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update the config
        self._update_config(instance, config_data)

        return instance

    def _extract_config_data(self, validated_data, integration_type):
        """Extract config fields from validated data"""
        config_data = {}

        if integration_type == 'EMAIL':
            keys = ['email_provider', 'from_email', 'from_name', 'smtp_host', 'smtp_port',
                   'smtp_username', 'smtp_password', 'use_tls', 'use_ssl',
                   'email_api_key', 'email_api_secret', 'email_api_url']
        elif integration_type == 'SMS':
            keys = ['sms_provider', 'account_sid', 'auth_token', 'from_number',
                   'sms_api_key', 'api_username', 'aws_access_key', 'aws_secret_key', 'aws_region']
        elif integration_type == 'PUSH':
            keys = ['push_provider', 'firebase_server_key', 'firebase_project_id',
                   'apns_certificate', 'apns_private_key', 'apns_team_id', 'apns_key_id']
        else:
            keys = []

        for key in keys:
            if key in validated_data:
                config_data[key] = validated_data.pop(key)

        return config_data

    def _create_config(self, integration, integration_type, config_data):
        """Create the config model for the integration"""
        if integration_type == 'EMAIL' and config_data:
            EmailConfiguration.objects.create(
                integration=integration,
                provider=config_data.get('email_provider', 'SMTP'),
                from_email=config_data.get('from_email', ''),
                from_name=config_data.get('from_name', ''),
                smtp_host=config_data.get('smtp_host', ''),
                smtp_port=config_data.get('smtp_port', 587),
                smtp_username=config_data.get('smtp_username', ''),
                smtp_password=config_data.get('smtp_password', ''),
                use_tls=config_data.get('use_tls', True),
                use_ssl=config_data.get('use_ssl', False),
                api_key=config_data.get('email_api_key', ''),
                api_secret=config_data.get('email_api_secret', ''),
                api_url=config_data.get('email_api_url', '')
            )
        elif integration_type == 'SMS' and config_data:
            SMSConfiguration.objects.create(
                integration=integration,
                provider=config_data.get('sms_provider', 'AFRICASTALKING'),
                account_sid=config_data.get('account_sid', ''),
                auth_token=config_data.get('auth_token', ''),
                from_number=config_data.get('from_number', ''),
                api_key=config_data.get('sms_api_key', ''),
                api_username=config_data.get('api_username', ''),
                aws_access_key=config_data.get('aws_access_key', ''),
                aws_secret_key=config_data.get('aws_secret_key', ''),
                aws_region=config_data.get('aws_region', 'us-east-1')
            )
        elif integration_type == 'PUSH' and config_data:
            PushConfiguration.objects.create(
                integration=integration,
                provider=config_data.get('push_provider', 'FIREBASE'),
                firebase_server_key=config_data.get('firebase_server_key', ''),
                firebase_project_id=config_data.get('firebase_project_id', ''),
                apns_certificate=config_data.get('apns_certificate', ''),
                apns_private_key=config_data.get('apns_private_key', ''),
                apns_team_id=config_data.get('apns_team_id', ''),
                apns_key_id=config_data.get('apns_key_id', '')
            )

    def _update_config(self, integration, config_data):
        """Update the config model for the integration"""
        if integration.integration_type == 'EMAIL':
            config, created = EmailConfiguration.objects.get_or_create(integration=integration)
            if 'email_provider' in config_data:
                config.provider = config_data['email_provider']
            if 'from_email' in config_data:
                config.from_email = config_data['from_email']
            if 'from_name' in config_data:
                config.from_name = config_data['from_name']
            if 'smtp_host' in config_data:
                config.smtp_host = config_data['smtp_host']
            if 'smtp_port' in config_data:
                config.smtp_port = config_data['smtp_port']
            if 'smtp_username' in config_data:
                config.smtp_username = config_data['smtp_username']
            if config_data.get('smtp_password'):
                config.smtp_password = config_data['smtp_password']
            if 'use_tls' in config_data:
                config.use_tls = config_data['use_tls']
            if 'use_ssl' in config_data:
                config.use_ssl = config_data['use_ssl']
            if config_data.get('email_api_key'):
                config.api_key = config_data['email_api_key']
            if config_data.get('email_api_secret'):
                config.api_secret = config_data['email_api_secret']
            if 'email_api_url' in config_data:
                config.api_url = config_data['email_api_url']
            config.save()

        elif integration.integration_type == 'SMS':
            config, created = SMSConfiguration.objects.get_or_create(integration=integration)
            if 'sms_provider' in config_data:
                config.provider = config_data['sms_provider']
            if config_data.get('account_sid'):
                config.account_sid = config_data['account_sid']
            if config_data.get('auth_token'):
                config.auth_token = config_data['auth_token']
            if 'from_number' in config_data:
                config.from_number = config_data['from_number']
            if config_data.get('sms_api_key'):
                config.api_key = config_data['sms_api_key']
            if 'api_username' in config_data:
                config.api_username = config_data['api_username']
            if config_data.get('aws_access_key'):
                config.aws_access_key = config_data['aws_access_key']
            if config_data.get('aws_secret_key'):
                config.aws_secret_key = config_data['aws_secret_key']
            if 'aws_region' in config_data:
                config.aws_region = config_data['aws_region']
            config.save()

        elif integration.integration_type == 'PUSH':
            config, created = PushConfiguration.objects.get_or_create(integration=integration)
            if 'push_provider' in config_data:
                config.provider = config_data['push_provider']
            if config_data.get('firebase_server_key'):
                config.firebase_server_key = config_data['firebase_server_key']
            if 'firebase_project_id' in config_data:
                config.firebase_project_id = config_data['firebase_project_id']
            if 'apns_certificate' in config_data:
                config.apns_certificate = config_data['apns_certificate']
            if config_data.get('apns_private_key'):
                config.apns_private_key = config_data['apns_private_key']
            if 'apns_team_id' in config_data:
                config.apns_team_id = config_data['apns_team_id']
            if 'apns_key_id' in config_data:
                config.apns_key_id = config_data['apns_key_id']
            config.save()


class EmailTemplateSerializer(serializers.ModelSerializer):
    """Serializer for Email Templates"""
    class Meta:
        model = EmailTemplate
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class SMSTemplateSerializer(serializers.ModelSerializer):
    """Serializer for SMS Templates"""
    class Meta:
        model = SMSTemplate
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class PushTemplateSerializer(serializers.ModelSerializer):
    """Serializer for Push Templates"""
    class Meta:
        model = PushTemplate
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']
