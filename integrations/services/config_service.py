"""
Centralized Integration Configuration Service

Provides unified access to all integration settings with:
- Automatic decryption of secrets
- Default values when DB settings not configured
- Type-safe configuration access
- Health check capabilities
"""
from typing import Dict, Any, Optional, Tuple
from django.core.cache import cache
from decimal import Decimal
import logging

from integrations.models import (
    Integrations, MpesaSettings, CardPaymentSettings, 
    PayPalSettings, KRASettings
)
from notifications.models import (
    NotificationIntegration, EmailConfiguration, 
    SMSConfiguration, PushConfiguration
)
from integrations.utils import Crypto

logger = logging.getLogger(__name__)


class IntegrationConfigService:
    """
    Centralized service for managing integration configurations.
    Provides defaults when DB settings don't exist and handles decryption.
    """
    
    # Default configurations (used when DB settings not set)
    DEFAULT_MPESA_CONFIG = {
        'consumer_key': '',
        'consumer_secret': '',
        'passkey': '',
        'short_code': '174379',  # Test paybill
        'base_url': 'https://sandbox.safaricom.co.ke',
        'callback_base_url': '',
        'initiator_name': '',
        'security_credential': '',
        'initiator_password': '',
    }
    
    DEFAULT_KRA_CONFIG = {
        'mode': 'sandbox',
        'base_url': 'https://api.sandbox.kra.go.ke',
        'kra_pin': '',
        'branch_code': '',
        'client_id': '',
        'client_secret': '',
        'username': '',
        'password': '',
        'token_path': '/oauth/token',
        'invoice_path': '/etims/v1/invoices',
        'invoice_status_path': '/etims/v1/invoices/status',
        'certificate_path': '/etims/v1/certificates',
        'compliance_path': '/etims/v1/compliance',
        'sync_path': '/etims/v1/sync',
    }
    
    DEFAULT_SMS_CONFIG = {
        'provider': 'AFRICASTALKING',
        'api_key': '',
        'api_username': 'sandbox',  # AfricasTalking sandbox username
        'from_number': '',
    }
    
    DEFAULT_EMAIL_CONFIG = {
        'provider': 'SMTP',
        'from_email': 'noreply@bengoerp.com',
        'from_name': 'BengoERP',
        'smtp_host': 'smtp.gmail.com',
        'smtp_port': 587,
        'smtp_username': '',
        'smtp_password': '',
        'use_tls': True,
        'use_ssl': False,
    }
    
    DEFAULT_CARD_CONFIG = {
        'provider': 'STRIPE',
        'is_test_mode': True,
        'api_key': '',
        'public_key': '',
        'webhook_secret': '',
        'base_url': 'https://api.stripe.com',
        'default_currency': 'KES',
    }
    
    @classmethod
    def get_mpesa_config(cls, decrypt_secrets: bool = True) -> Dict[str, Any]:
        """
        Get M-Pesa configuration with optional decryption.
        Returns defaults if not configured in DB.
        """
        cache_key = 'mpesa_config_decrypted' if decrypt_secrets else 'mpesa_config_raw'
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            integration = Integrations.objects.filter(
                integration_type='PAYMENT',
                is_active=True,
                name='MPESA'
            ).first()
            
            if not integration:
                logger.warning("M-Pesa integration not found, using defaults")
                cache.set(cache_key, cls.DEFAULT_MPESA_CONFIG, timeout=300)
                return cls.DEFAULT_MPESA_CONFIG
            
            settings = MpesaSettings.objects.filter(integration=integration).first()
            if not settings:
                logger.warning("M-Pesa settings not found, using defaults")
                cache.set(cache_key, cls.DEFAULT_MPESA_CONFIG, timeout=300)
                return cls.DEFAULT_MPESA_CONFIG
            
            config = {
                'consumer_key': cls._decrypt_if_needed(settings.consumer_key) if decrypt_secrets else settings.consumer_key,
                'consumer_secret': cls._decrypt_if_needed(settings.consumer_secret) if decrypt_secrets else settings.consumer_secret,
                'passkey': cls._decrypt_if_needed(settings.passkey) if decrypt_secrets else settings.passkey,
                'security_credential': cls._decrypt_if_needed(settings.security_credential) if decrypt_secrets else settings.security_credential,
                'short_code': settings.short_code or '',
                'base_url': settings.base_url,
                'callback_base_url': settings.callback_base_url or '',
                'initiator_name': settings.initiator_name or '',
                'initiator_password': cls._decrypt_if_needed(settings.initiator_password) if decrypt_secrets else settings.initiator_password,
            }
            
            cache.set(cache_key, config, timeout=300)
            return config
            
        except Exception as e:
            logger.error(f"Error getting M-Pesa config: {str(e)}")
            return cls.DEFAULT_MPESA_CONFIG
    
    @classmethod
    def get_kra_config(cls, decrypt_secrets: bool = True) -> Dict[str, Any]:
        """
        Get KRA eTIMS configuration with optional decryption.
        Returns defaults if not configured in DB.
        """
        cache_key = 'kra_config_decrypted' if decrypt_secrets else 'kra_config_raw'
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            settings = KRASettings.objects.order_by('-updated_at').first()
            
            if not settings:
                logger.warning("KRA settings not found, using defaults")
                cache.set(cache_key, cls.DEFAULT_KRA_CONFIG, timeout=300)
                return cls.DEFAULT_KRA_CONFIG
            
            config = {
                'mode': settings.mode,
                'base_url': settings.base_url,
                'kra_pin': settings.kra_pin or '',
                'branch_code': settings.branch_code or '',
                'client_id': cls._decrypt_if_needed(settings.client_id) if decrypt_secrets else settings.client_id,
                'client_secret': cls._decrypt_if_needed(settings.client_secret) if decrypt_secrets else settings.client_secret,
                'username': settings.username or '',
                'password': cls._decrypt_if_needed(settings.password) if decrypt_secrets else settings.password,
                'token_path': settings.token_path,
                'invoice_path': settings.invoice_path,
                'invoice_status_path': settings.invoice_status_path,
                'certificate_path': settings.certificate_path,
                'compliance_path': settings.compliance_path,
                'sync_path': settings.sync_path,
            }
            
            cache.set(cache_key, config, timeout=300)
            return config
            
        except Exception as e:
            logger.error(f"Error getting KRA config: {str(e)}")
            return cls.DEFAULT_KRA_CONFIG
    
    @classmethod
    def get_sms_config(cls, decrypt_secrets: bool = True) -> Dict[str, Any]:
        """
        Get SMS configuration with optional decryption.
        Returns defaults if not configured in DB.
        """
        cache_key = 'sms_config_decrypted' if decrypt_secrets else 'sms_config_raw'
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            integration = NotificationIntegration.objects.filter(
                integration_type='SMS',
                is_active=True,
                is_default=True
            ).first()
            
            if not integration:
                logger.warning("SMS integration not found, using defaults")
                cache.set(cache_key, cls.DEFAULT_SMS_CONFIG, timeout=300)
                return cls.DEFAULT_SMS_CONFIG
            
            settings = SMSConfiguration.objects.filter(integration=integration).first()
            if not settings:
                logger.warning("SMS settings not found, using defaults")
                cache.set(cache_key, cls.DEFAULT_SMS_CONFIG, timeout=300)
                return cls.DEFAULT_SMS_CONFIG
            
            config = {
                'provider': settings.provider,
                'api_key': cls._decrypt_if_needed(settings.api_key) if decrypt_secrets else settings.api_key,
                'api_username': settings.api_username or 'sandbox',
                'auth_token': cls._decrypt_if_needed(settings.auth_token) if decrypt_secrets else settings.auth_token,
                'account_sid': cls._decrypt_if_needed(settings.account_sid) if decrypt_secrets else settings.account_sid,
                'from_number': settings.from_number or '',
                'aws_access_key': cls._decrypt_if_needed(settings.aws_access_key) if decrypt_secrets else settings.aws_access_key,
                'aws_secret_key': cls._decrypt_if_needed(settings.aws_secret_key) if decrypt_secrets else settings.aws_secret_key,
                'aws_region': settings.aws_region or 'us-east-1',
            }
            
            cache.set(cache_key, config, timeout=300)
            return config
            
        except Exception as e:
            logger.error(f"Error getting SMS config: {str(e)}")
            return cls.DEFAULT_SMS_CONFIG
    
    @classmethod
    def get_email_config(cls, decrypt_secrets: bool = True) -> Dict[str, Any]:
        """
        Get Email configuration with optional decryption.
        Returns defaults if not configured in DB.
        """
        cache_key = 'email_config_decrypted' if decrypt_secrets else 'email_config_raw'
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            integration = NotificationIntegration.objects.filter(
                integration_type='EMAIL',
                is_active=True,
                is_default=True
            ).first()
            
            if not integration:
                logger.warning("Email integration not found, using defaults")
                cache.set(cache_key, cls.DEFAULT_EMAIL_CONFIG, timeout=300)
                return cls.DEFAULT_EMAIL_CONFIG
            
            settings = EmailConfiguration.objects.filter(integration=integration).first()
            if not settings:
                logger.warning("Email settings not found, using defaults")
                cache.set(cache_key, cls.DEFAULT_EMAIL_CONFIG, timeout=300)
                return cls.DEFAULT_EMAIL_CONFIG
            
            config = {
                'provider': settings.provider,
                'from_email': settings.from_email,
                'from_name': settings.from_name,
                'smtp_host': settings.smtp_host,
                'smtp_port': settings.smtp_port,
                'smtp_username': settings.smtp_username or '',
                'smtp_password': cls._decrypt_if_needed(settings.smtp_password) if decrypt_secrets else settings.smtp_password,
                'use_tls': settings.use_tls,
                'use_ssl': settings.use_ssl,
                'api_key': cls._decrypt_if_needed(settings.api_key) if decrypt_secrets else settings.api_key,
                'api_secret': cls._decrypt_if_needed(settings.api_secret) if decrypt_secrets else settings.api_secret,
                'api_url': settings.api_url or '',
            }
            
            cache.set(cache_key, config, timeout=300)
            return config
            
        except Exception as e:
            logger.error(f"Error getting Email config: {str(e)}")
            return cls.DEFAULT_EMAIL_CONFIG
    
    @classmethod
    def get_card_payment_config(cls, decrypt_secrets: bool = True) -> Dict[str, Any]:
        """
        Get Card Payment configuration with optional decryption.
        Returns defaults if not configured in DB.
        """
        cache_key = 'card_config_decrypted' if decrypt_secrets else 'card_config_raw'
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            integration = Integrations.objects.filter(
                integration_type='PAYMENT',
                is_active=True,
                name='CARD'
            ).first()
            
            if not integration:
                logger.warning("Card payment integration not found, using defaults")
                cache.set(cache_key, cls.DEFAULT_CARD_CONFIG, timeout=300)
                return cls.DEFAULT_CARD_CONFIG
            
            settings = CardPaymentSettings.objects.filter(integration=integration).first()
            if not settings:
                logger.warning("Card payment settings not found, using defaults")
                cache.set(cache_key, cls.DEFAULT_CARD_CONFIG, timeout=300)
                return cls.DEFAULT_CARD_CONFIG
            
            config = {
                'provider': settings.provider,
                'is_test_mode': settings.is_test_mode,
                'api_key': cls._decrypt_if_needed(settings.api_key) if decrypt_secrets else settings.api_key,
                'public_key': settings.public_key,
                'webhook_secret': cls._decrypt_if_needed(settings.webhook_secret) if decrypt_secrets else settings.webhook_secret,
                'base_url': settings.base_url,
                'webhook_url': settings.webhook_url,
                'success_url': settings.success_url,
                'cancel_url': settings.cancel_url,
                'default_currency': settings.default_currency,
                'business_name': settings.business_name,
            }
            
            cache.set(cache_key, config, timeout=300)
            return config
            
        except Exception as e:
            logger.error(f"Error getting Card Payment config: {str(e)}")
            return cls.DEFAULT_CARD_CONFIG
    
    @classmethod
    def _decrypt_if_needed(cls, value: Optional[str]) -> str:
        """
        Decrypt a value if it's encrypted (contains gAAAAA marker).
        Returns empty string if value is None.
        """
        if not value:
            return ''
        
        try:
            if isinstance(value, str) and 'gAAAAA' in value:
                return Crypto(value, 'decrypt').decrypt()
            return value
        except Exception as e:
            logger.error(f"Error decrypting value: {str(e)}")
            return ''
    
    @classmethod
    def test_mpesa_connection(cls) -> Tuple[bool, str]:
        """
        Test M-Pesa API connectivity by attempting to get access token.
        Returns (success, message)
        """
        try:
            from integrations.payments.mpesa_payment import MpesaPaymentService
            
            settings = MpesaPaymentService.get_settings()
            if not settings:
                return False, "M-Pesa settings not configured"
            
            # Try to get access token
            config = cls.get_mpesa_config(decrypt_secrets=True)
            consumer_key = config['consumer_key']
            consumer_secret = config['consumer_secret']
            
            if not consumer_key or not consumer_secret:
                return False, "M-Pesa consumer credentials not set"
            
            import requests
            auth_resp = requests.get(
                f"{config['base_url']}/oauth/v1/generate?grant_type=client_credentials",
                auth=(consumer_key, consumer_secret),
                timeout=10,
            )
            
            if auth_resp.ok and auth_resp.json().get('access_token'):
                return True, "M-Pesa connection successful"
            else:
                return False, f"M-Pesa authentication failed: {auth_resp.text}"
                
        except Exception as e:
            return False, f"M-Pesa connection error: {str(e)}"
    
    @classmethod
    def test_kra_connection(cls) -> Tuple[bool, str]:
        """
        Test KRA API connectivity by attempting to get access token.
        Returns (success, message)
        """
        try:
            from integrations.services import KRAService
            
            kra_service = KRAService()
            success, result = kra_service.get_access_token()
            
            if success:
                return True, "KRA connection successful"
            else:
                return False, f"KRA authentication failed: {result}"
                
        except Exception as e:
            return False, f"KRA connection error: {str(e)}"
    
    @classmethod
    def test_sms_connection(cls) -> Tuple[bool, str]:
        """
        Test SMS provider connectivity.
        Returns (success, message)
        """
        try:
            config = cls.get_sms_config(decrypt_secrets=True)
            provider = config.get('provider')
            
            if provider == 'AFRICASTALKING':
                api_key = config.get('api_key')
                username = config.get('api_username', 'sandbox')
                
                if not api_key:
                    return False, "AfricasTalking API key not set"
                
                # Test with sandbox endpoint
                import requests
                headers = {
                    'apiKey': api_key,
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Accept': 'application/json',
                }
                
                # Use the user data endpoint as a connectivity test
                resp = requests.get(
                    'https://api.sandbox.africastalking.com/version1/user',
                    headers={'apiKey': api_key},
                    params={'username': username},
                    timeout=10
                )
                
                if resp.ok:
                    return True, "AfricasTalking connection successful"
                else:
                    return False, f"AfricasTalking connection failed: {resp.text}"
            
            elif provider == 'TWILIO':
                account_sid = config.get('account_sid')
                auth_token = config.get('auth_token')
                
                if not account_sid or not auth_token:
                    return False, "Twilio credentials not set"
                
                return True, "Twilio configured (connection test requires live credentials)"
            
            else:
                return False, f"Unsupported SMS provider: {provider}"
                
        except Exception as e:
            return False, f"SMS connection error: {str(e)}"
    
    @classmethod
    def test_email_connection(cls) -> Tuple[bool, str]:
        """
        Test Email provider connectivity.
        Returns (success, message)
        """
        try:
            config = cls.get_email_config(decrypt_secrets=True)
            provider = config.get('provider')
            
            if provider == 'SMTP':
                import smtplib
                
                smtp_host = config.get('smtp_host')
                smtp_port = config.get('smtp_port', 587)
                smtp_username = config.get('smtp_username')
                smtp_password = config.get('smtp_password')
                
                if not smtp_host:
                    return False, "SMTP host not configured"
                
                try:
                    if config.get('use_ssl'):
                        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
                    else:
                        server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
                        if config.get('use_tls'):
                            server.starttls()
                    
                    if smtp_username and smtp_password:
                        server.login(smtp_username, smtp_password)
                    
                    server.quit()
                    return True, "SMTP connection successful"
                    
                except Exception as e:
                    return False, f"SMTP connection failed: {str(e)}"
            
            else:
                return True, f"{provider} configured (API connection test requires credentials)"
                
        except Exception as e:
            return False, f"Email connection error: {str(e)}"
    
    @classmethod
    def get_all_integration_status(cls) -> Dict[str, Dict[str, Any]]:
        """
        Get status of all integrations with connectivity tests.
        Useful for system health dashboard.
        """
        return {
            'mpesa': {
                'configured': cls.is_integration_configured('MPESA'),
                'active': cls.is_integration_active('MPESA'),
                'connection': cls.test_mpesa_connection(),
            },
            'kra': {
                'configured': cls.is_kra_configured(),
                'connection': cls.test_kra_connection(),
            },
            'sms': {
                'configured': cls.is_sms_configured(),
                'connection': cls.test_sms_connection(),
            },
            'email': {
                'configured': cls.is_email_configured(),
                'connection': cls.test_email_connection(),
            },
            'card_payment': {
                'configured': cls.is_integration_configured('CARD'),
                'active': cls.is_integration_active('CARD'),
            },
        }
    
    @classmethod
    def is_integration_configured(cls, integration_name: str) -> bool:
        """Check if a payment integration is configured in DB."""
        return Integrations.objects.filter(name=integration_name).exists()
    
    @classmethod
    def is_integration_active(cls, integration_name: str) -> bool:
        """Check if a payment integration is active."""
        return Integrations.objects.filter(name=integration_name, is_active=True).exists()
    
    @classmethod
    def is_kra_configured(cls) -> bool:
        """Check if KRA settings are configured."""
        return KRASettings.objects.exists()
    
    @classmethod
    def is_sms_configured(cls) -> bool:
        """Check if SMS is configured."""
        return SMSConfiguration.objects.exists()
    
    @classmethod
    def is_email_configured(cls) -> bool:
        """Check if Email is configured."""
        return EmailConfiguration.objects.exists()
    
    @classmethod
    def clear_config_cache(cls):
        """Clear all integration configuration caches."""
        cache_keys = [
            'mpesa_config_decrypted', 'mpesa_config_raw',
            'kra_config_decrypted', 'kra_config_raw',
            'sms_config_decrypted', 'sms_config_raw',
            'email_config_decrypted', 'email_config_raw',
            'card_config_decrypted', 'card_config_raw',
        ]
        for key in cache_keys:
            cache.delete(key)
        
        logger.info("Integration configuration cache cleared")
        return True

