"""
Integration services entry point.
Provides easy access to all integration services from a single import.
Notification services have been moved to the centralized notifications app.
"""

# Import notification services from centralized app
from notifications.services import (
    EmailService, SMSService, PushNotificationService, NotificationService,
    send_email_task, send_sms_task, send_push_notification_task, send_notification_task
)

# Import configuration service
from .services.config_service import IntegrationConfigService

__all__ = [
    # Notification services (redirected to centralized app)
    'EmailService',
    'SMSService', 
    'PushNotificationService',
    'NotificationService',
    'send_email_task',
    'send_sms_task',
    'send_push_notification_task',
    'send_notification_task',
    
    # Integration services
    'KRAService',
    'WebhookDeliveryService',
    'IntegrationConfigService',
]

# Factory functions - redirect to centralized notifications
def get_email_service(integration=None):
    """
    Get an email service instance from centralized notifications app
    
    Args:
        integration: Optional specific integration to use
        
    Returns:
        EmailService instance
    """
    return EmailService(integration=integration)

def get_sms_service(integration=None, provider=None):
    """
    Get an SMS service instance from centralized notifications app
    
    Args:
        integration: Optional specific integration to use
        provider: Optional provider override
        
    Returns:
        SMSService instance
    """
    return SMSService(integration=integration, provider=provider)

def get_notification_service(integration=None):
    """
    Get a notification service instance from centralized notifications app
    
    Args:
        integration: Optional specific integration to use
        
    Returns:
        NotificationService instance
    """
    return NotificationService(integration=integration)


# ---------------------------
# KRA eTIMS Service
# ---------------------------
import requests
from decimal import Decimal
from django.utils import timezone

from .models import KRASettings, KRACertificateRequest, KRAComplianceCheck, WebhookEndpoint, WebhookEvent
from .utils import Crypto
import hmac
import hashlib
import json
import time
from typing import Optional
try:
    from core.background_jobs import submit_threaded_task  # type: ignore
except Exception:
    def submit_threaded_task(pool_name: str, task_func, *args, **kwargs):  # type: ignore
        return task_func(*args, **kwargs)


class KRAService:
    """
    Minimal KRA eTIMS client.
    Implements token retrieval and invoice submission hooks.
    """

    def __init__(self):
        self.settings = KRASettings.objects.order_by('-updated_at').first()

    def _get_base_url(self) -> str:
        if not self.settings:
            return 'https://api.sandbox.kra.go.ke'
        return self.settings.base_url

    def _decrypt(self, value) -> str:
        val = value or ''
        return Crypto(val, 'decrypt').decrypt() if isinstance(val, str) and 'gAAAAA' in val else val

    def get_access_token(self) -> tuple[bool, str]:
        if not self.settings:
            return False, 'KRA settings not configured'

        client_id = self._decrypt(self.settings.client_id)
        client_secret = self._decrypt(self.settings.client_secret)
        username = self.settings.username or ''
        password = self._decrypt(self.settings.password or '')

        url = f"{self._get_base_url()}{self.settings.token_path}"
        try:
            data = {
                'grant_type': 'password',
                'client_id': client_id,
                'client_secret': client_secret,
                'username': username,
                'password': password,
            }
            resp = requests.post(url, data=data, timeout=30)
            resp.raise_for_status()
            token = resp.json().get('access_token')
            if not token:
                return False, 'Missing access_token in response'
            return True, str(token)
        except Exception as exc:
            return False, str(exc)

    def submit_invoice(self, invoice_payload: dict) -> tuple[bool, dict | str]:
        """
        Submit invoice to eTIMS. The payload should already be mapped to the KRA schema
        by the caller.
        """
        ok, token_or_err = self.get_access_token()
        if not ok:
            return False, token_or_err

        if not self.settings:
            return False, 'KRA settings not configured'
        url = f"{self._get_base_url()}{self.settings.invoice_path}"
        headers = {
            'Authorization': f"Bearer {token_or_err}",
            'Content-Type': 'application/json'
        }
        try:
            resp = requests.post(url, json=invoice_payload, headers=headers, timeout=60)
            resp.raise_for_status()
            return True, resp.json()
        except Exception as exc:
            return False, str(exc)

    def get_invoice_status(self, reference: str) -> tuple[bool, dict | str]:
        ok, token_or_err = self.get_access_token()
        if not ok:
            return False, token_or_err

        if not self.settings:
            return False, 'KRA settings not configured'
        url = f"{self._get_base_url()}{self.settings.invoice_status_path}"
        headers = {'Authorization': f"Bearer {token_or_err}"}
        try:
            resp = requests.get(url, params={'ref': reference}, headers=headers, timeout=30)
            resp.raise_for_status()
            return True, resp.json()
        except Exception as exc:
            return False, str(exc)

    def validate_pin(self, kra_pin: str) -> tuple[bool, dict | str]:
        """Basic placeholder for PIN validation endpoint if exposed by KRA. Uses token and calls a hypothetical validate path."""
        ok, token_or_err = self.get_access_token()
        if not ok:
            return False, token_or_err
        # If KRA exposes a PIN validation endpoint, wire here; else perform basic format check
        try:
            # Simple format sanity: starts with P and has digits
            import re
            if not re.match(r'^P[0-9A-Z]{9,12}$', kra_pin.upper()):
                return False, 'Invalid PIN format'
            # If there is a remote endpoint, one could do:
            # url = f"{self._get_base_url()}/etims/v1/pin/validate"
            # headers = {'Authorization': f"Bearer {token_or_err}"}
            # resp = requests.get(url, params={'pin': kra_pin}, headers=headers, timeout=30)
            # resp.raise_for_status()
            # return True, resp.json()
            return True, {'valid': True, 'pin': kra_pin.upper()}
        except Exception as exc:
            return False, str(exc)

    def get_tax_certificate(self, tax_type: str, period: str) -> tuple[bool, dict | str]:
        ok, token_or_err = self.get_access_token()
        if not ok:
            return False, token_or_err
        if not self.settings:
            return False, 'KRA settings not configured'
        url = f"{self._get_base_url()}{getattr(self.settings, 'certificate_path', '/etims/v1/certificates')}"
        headers = {'Authorization': f"Bearer {token_or_err}"}
        payload = {'type': tax_type, 'period': period}
        req_log = None
        try:
            # Create request log
            try:
                req_log = KRACertificateRequest.objects.create(
                    cert_type=tax_type,
                    period=period,
                    status='requested',
                )
            except Exception:
                req_log = None
            resp = requests.get(url, params=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            # Update log
            if req_log:
                try:
                    req_log.status = 'completed'
                    req_log.response_payload = data
                    req_log.save(update_fields=['status', 'response_payload'])
                except Exception:
                    pass
            return True, data
        except Exception as exc:
            if req_log:
                try:
                    req_log.status = 'failed'
                    # store error as string to avoid type issues on strict backends
                    req_log.response_payload = {'error': str(exc)}  # type: ignore[assignment]
                    req_log.save(update_fields=['status', 'response_payload'])
                except Exception:
                    pass
            return False, str(exc)

    def check_compliance(self, kra_pin: str) -> tuple[bool, dict | str]:
        ok, token_or_err = self.get_access_token()
        if not ok:
            return False, token_or_err
        if not self.settings:
            return False, 'KRA settings not configured'
        url = f"{self._get_base_url()}{getattr(self.settings, 'compliance_path', '/etims/v1/compliance')}"
        headers = {'Authorization': f"Bearer {token_or_err}"}
        try:
            resp = requests.get(url, params={'pin': kra_pin}, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            is_compliant = bool(data.get('compliant')) if isinstance(data, dict) else False
            # Log compliance check
            try:
                KRAComplianceCheck.objects.create(
                    kra_pin=kra_pin,
                    is_compliant=is_compliant,
                    response_payload=data
                )
            except Exception:
                pass
            return True, data
        except Exception as exc:
            try:
                KRAComplianceCheck.objects.create(
                    kra_pin=kra_pin,
                    is_compliant=False,
                    response_payload={'error': str(exc)}
                )
            except Exception:
                pass
            return False, str(exc)

    def sync_tax_data(self, start_date: str, end_date: str) -> tuple[bool, dict | str]:
        ok, token_or_err = self.get_access_token()
        if not ok:
            return False, token_or_err
        if not self.settings:
            return False, 'KRA settings not configured'
        url = f"{self._get_base_url()}{getattr(self.settings, 'sync_path', '/etims/v1/sync')}"
        headers = {'Authorization': f"Bearer {token_or_err}", 'Content-Type': 'application/json'}
        try:
            resp = requests.post(url, json={'start_date': start_date, 'end_date': end_date}, headers=headers, timeout=60)
            resp.raise_for_status()
            return True, resp.json()
        except Exception as exc:
            return False, str(exc)


class WebhookDeliveryService:
    """Deliver webhook events with HMAC signing and retries."""

    MAX_ATTEMPTS = 3
    TIMEOUT = 15

    @staticmethod
    def _sign_payload(secret: Optional[str], payload: dict, timestamp: str) -> str:
        if not secret:
            return ''
        body = json.dumps({'timestamp': timestamp, 'payload': payload}, separators=(',', ':'), ensure_ascii=False)
        signature = hmac.new(secret.encode('utf-8'), body.encode('utf-8'), hashlib.sha256).hexdigest()
        return signature

    @classmethod
    def deliver_event(cls, event_id: int) -> bool:
        try:
            event = WebhookEvent.objects.select_related('endpoint').get(pk=event_id)
        except WebhookEvent.DoesNotExist:
            return False

        endpoint = event.endpoint
        payload = event.payload or {}
        attempts = event.attempts or 0

        for attempt in range(attempts, cls.MAX_ATTEMPTS):
            try:
                timestamp = timezone.now().isoformat()
                signature = cls._sign_payload(getattr(endpoint, 'secret', '') or '', payload, timestamp)
                headers = {
                    'Content-Type': 'application/json',
                    'X-Webhook-Timestamp': timestamp,
                    'X-Webhook-Signature': signature,
                    'X-Webhook-Event': event.event_type,
                }
                resp = requests.post(endpoint.url, json=payload, headers=headers, timeout=cls.TIMEOUT)
                if 200 <= resp.status_code < 300:
                    WebhookEvent.objects.filter(pk=event.pk).update(
                        status='delivered',
                        attempts=attempt + 1,
                        last_error='',
                        updated_at=timezone.now()
                    )
                    return True
                else:
                    WebhookEvent.objects.filter(pk=event.pk).update(
                        status='retrying',
                        attempts=attempt + 1,
                        last_error=f"HTTP {resp.status_code}: {resp.text[:500]}",
                        updated_at=timezone.now()
                    )
            except Exception as exc:
                WebhookEvent.objects.filter(pk=event.pk).update(
                    status='retrying',
                    attempts=attempt + 1,
                    last_error=str(exc)[:500],
                    updated_at=timezone.now()
                )

            backoff = min(2 ** attempt, 8)
            time.sleep(backoff)

        WebhookEvent.objects.filter(pk=event.pk).update(status='failed', updated_at=timezone.now())
        return False

    @classmethod
    def schedule_delivery(cls, event_id: int) -> str:
        job_id = submit_threaded_task('webhooks', cls.deliver_event, event_id)
        return str(job_id)
