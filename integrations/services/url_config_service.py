"""
URL Configuration Service for Integrations

Provides centralized URL management for:
- Webhook URLs (backend endpoints that receive callbacks)
- Callback URLs (frontend pages users are redirected to)
- Public share links (customer-facing pages)

URLs are auto-configured based on Django settings but can be overridden
via environment variables or admin configuration.
"""

import logging
from typing import Optional, Dict, Any
from urllib.parse import urljoin, urlparse
from django.conf import settings

logger = logging.getLogger(__name__)


class URLConfigService:
    """
    Centralized service for managing integration URLs.

    Provides:
    - Auto-detection of base URLs from settings
    - HTTPS enforcement in production
    - Idempotent URL generation (same input = same output)
    - Override support from settings or database
    """

    # Default path mappings for auto-configuration
    DEFAULT_PATHS = {
        # M-Pesa
        'mpesa_callback': '/api/v1/finance/payment/mpesa/callback/',
        'mpesa_timeout': '/api/v1/finance/payment/mpesa/timeout/',
        'mpesa_validation': '/api/v1/finance/payment/mpesa/validation/',
        'mpesa_confirmation': '/api/v1/finance/payment/mpesa/confirmation/',

        # Paystack
        'paystack_webhook': '/api/v1/finance/payment/paystack/webhook/',
        'paystack_callback': '/public/payment/callback',  # Frontend page

        # PayPal
        'paypal_return': '/public/payment/callback',  # Frontend page
        'paypal_cancel': '/public/payment/cancel',  # Frontend page
        'paypal_webhook': '/api/v1/finance/payment/paypal/webhook/',

        # Stripe
        'stripe_webhook': '/api/v1/finance/payment/stripe/webhook/',
        'stripe_success': '/public/payment/callback',
        'stripe_cancel': '/public/payment/cancel',

        # Public document sharing
        'public_invoice': '/public/invoice/{id}/{token}',
        'public_quotation': '/public/quotation/{id}/{token}',
    }

    @classmethod
    def get_frontend_url(cls) -> str:
        """
        Get the frontend base URL.

        Returns HTTPS URL in production if FORCE_HTTPS is enabled.
        """
        url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        return cls._ensure_https(url.rstrip('/'))

    @classmethod
    def get_backend_url(cls) -> str:
        """
        Get the backend API base URL.

        Returns HTTPS URL in production if FORCE_HTTPS is enabled.
        """
        url = getattr(settings, 'BACKEND_URL', 'http://localhost:8000')
        return cls._ensure_https(url.rstrip('/'))

    @classmethod
    def _ensure_https(cls, url: str) -> str:
        """
        Ensure URL uses HTTPS if FORCE_HTTPS is enabled.
        """
        force_https = getattr(settings, 'FORCE_HTTPS', False)
        if force_https and url.startswith('http://'):
            return 'https://' + url[7:]
        return url

    @classmethod
    def get_webhook_url(cls, integration: str, endpoint: str) -> str:
        """
        Get webhook URL for a specific integration endpoint.

        Webhooks always use the backend URL since they hit API endpoints.

        Args:
            integration: Integration name (mpesa, paystack, paypal, stripe)
            endpoint: Endpoint name (callback, webhook, validation, etc.)

        Returns:
            Full webhook URL
        """
        # Check for setting override first
        setting_key = f'{integration.upper()}_{endpoint.upper()}_URL'
        override_url = getattr(settings, setting_key, '')
        if override_url:
            return cls._ensure_https(override_url)

        # Auto-configure from default paths
        path_key = f'{integration}_{endpoint}'
        path = cls.DEFAULT_PATHS.get(path_key, '')

        if not path:
            logger.warning(f"No default path configured for {path_key}")
            return ''

        return f"{cls.get_backend_url()}{path}"

    @classmethod
    def get_callback_url(cls, integration: str, endpoint: str = 'callback') -> str:
        """
        Get callback/redirect URL for a specific integration.

        Callbacks use frontend URL since users are redirected there.

        Args:
            integration: Integration name (paystack, paypal, stripe)
            endpoint: Endpoint name (callback, return, cancel, success)

        Returns:
            Full callback URL
        """
        # Check for setting override first
        setting_key = f'{integration.upper()}_{endpoint.upper()}_URL'
        override_url = getattr(settings, setting_key, '')
        if override_url:
            return cls._ensure_https(override_url)

        # Auto-configure from default paths
        path_key = f'{integration}_{endpoint}'
        path = cls.DEFAULT_PATHS.get(path_key, '')

        if not path:
            # Default to generic callback page
            path = '/public/payment/callback'

        return f"{cls.get_frontend_url()}{path}"

    @classmethod
    def get_public_share_url(cls, doc_type: str, doc_id: int, token: str) -> str:
        """
        Get public share URL for a document.

        Always uses frontend URL with HTTPS in production.

        Args:
            doc_type: Document type (invoice, quotation)
            doc_id: Document ID
            token: Share token

        Returns:
            Full public share URL
        """
        path_key = f'public_{doc_type}'
        path_template = cls.DEFAULT_PATHS.get(path_key, f'/public/{doc_type}/{{id}}/{{token}}')
        path = path_template.format(id=doc_id, token=token)

        return f"{cls.get_frontend_url()}{path}"

    @classmethod
    def get_mpesa_urls(cls) -> Dict[str, str]:
        """
        Get all M-Pesa integration URLs.

        Returns:
            Dict with callback_url, timeout_url, validation_url, confirmation_url
        """
        return {
            'callback_url': cls.get_webhook_url('mpesa', 'callback'),
            'timeout_url': cls.get_webhook_url('mpesa', 'timeout'),
            'validation_url': cls.get_webhook_url('mpesa', 'validation'),
            'confirmation_url': cls.get_webhook_url('mpesa', 'confirmation'),
        }

    @classmethod
    def get_paystack_urls(cls) -> Dict[str, str]:
        """
        Get all Paystack integration URLs.

        Returns:
            Dict with webhook_url, callback_url
        """
        return {
            'webhook_url': cls.get_webhook_url('paystack', 'webhook'),
            'callback_url': cls.get_callback_url('paystack', 'callback'),
        }

    @classmethod
    def get_paypal_urls(cls) -> Dict[str, str]:
        """
        Get all PayPal integration URLs.

        Returns:
            Dict with webhook_url, return_url, cancel_url
        """
        return {
            'webhook_url': cls.get_webhook_url('paypal', 'webhook'),
            'return_url': cls.get_callback_url('paypal', 'return'),
            'cancel_url': cls.get_callback_url('paypal', 'cancel'),
        }

    @classmethod
    def get_stripe_urls(cls) -> Dict[str, str]:
        """
        Get all Stripe integration URLs.

        Returns:
            Dict with webhook_url, success_url, cancel_url
        """
        return {
            'webhook_url': cls.get_webhook_url('stripe', 'webhook'),
            'success_url': cls.get_callback_url('stripe', 'success'),
            'cancel_url': cls.get_callback_url('stripe', 'cancel'),
        }

    @classmethod
    def get_all_integration_urls(cls) -> Dict[str, Dict[str, str]]:
        """
        Get all integration URLs as a nested dictionary.

        Useful for displaying in admin or configuration UI.

        Returns:
            Dict keyed by integration name containing URL dicts
        """
        return {
            'frontend_base': cls.get_frontend_url(),
            'backend_base': cls.get_backend_url(),
            'mpesa': cls.get_mpesa_urls(),
            'paystack': cls.get_paystack_urls(),
            'paypal': cls.get_paypal_urls(),
            'stripe': cls.get_stripe_urls(),
        }

    @classmethod
    def update_integration_settings_urls(cls, integration: str) -> bool:
        """
        Update the database settings for an integration with auto-configured URLs.

        This is idempotent - calling multiple times has the same effect.

        Args:
            integration: Integration name to update

        Returns:
            True if settings were updated, False if no changes needed
        """
        try:
            if integration == 'mpesa':
                from integrations.models import MpesaSettings
                settings_obj = MpesaSettings.objects.first()
                if settings_obj:
                    urls = cls.get_mpesa_urls()
                    updated = False
                    if not settings_obj.callback_url or settings_obj.callback_url != urls['callback_url']:
                        settings_obj.callback_url = urls['callback_url']
                        updated = True
                    if hasattr(settings_obj, 'timeout_url') and (not settings_obj.timeout_url or settings_obj.timeout_url != urls['timeout_url']):
                        settings_obj.timeout_url = urls['timeout_url']
                        updated = True
                    if updated:
                        settings_obj.save()
                        logger.info(f"Updated M-Pesa settings URLs")
                    return updated

            elif integration == 'paystack':
                from integrations.models import PaystackSettings
                settings_obj = PaystackSettings.objects.first()
                if settings_obj:
                    urls = cls.get_paystack_urls()
                    updated = False
                    if not settings_obj.webhook_url or settings_obj.webhook_url != urls['webhook_url']:
                        settings_obj.webhook_url = urls['webhook_url']
                        updated = True
                    if not settings_obj.callback_url or settings_obj.callback_url != urls['callback_url']:
                        settings_obj.callback_url = urls['callback_url']
                        updated = True
                    if updated:
                        settings_obj.save()
                        logger.info(f"Updated Paystack settings URLs")
                    return updated

            elif integration == 'paypal':
                from integrations.models import PayPalSettings
                settings_obj = PayPalSettings.objects.first()
                if settings_obj:
                    urls = cls.get_paypal_urls()
                    updated = False
                    if hasattr(settings_obj, 'return_url') and (not settings_obj.return_url or settings_obj.return_url != urls['return_url']):
                        settings_obj.return_url = urls['return_url']
                        updated = True
                    if hasattr(settings_obj, 'cancel_url') and (not settings_obj.cancel_url or settings_obj.cancel_url != urls['cancel_url']):
                        settings_obj.cancel_url = urls['cancel_url']
                        updated = True
                    if updated:
                        settings_obj.save()
                        logger.info(f"Updated PayPal settings URLs")
                    return updated

            return False

        except Exception as e:
            logger.error(f"Error updating {integration} settings URLs: {e}")
            return False

    @classmethod
    def update_all_integration_urls(cls) -> Dict[str, bool]:
        """
        Update all integration settings with auto-configured URLs.

        This is idempotent - safe to call multiple times.

        Returns:
            Dict mapping integration name to update success status
        """
        results = {}
        for integration in ['mpesa', 'paystack', 'paypal']:
            try:
                results[integration] = cls.update_integration_settings_urls(integration)
            except Exception as e:
                logger.error(f"Error updating {integration} URLs: {e}")
                results[integration] = False
        return results
