from django.utils import timezone
from decimal import Decimal
import requests
import logging

from ..models import Integrations, MpesaSettings
from ..utils import Crypto
from ..services.config_service import IntegrationConfigService

logger = logging.getLogger(__name__)


class MpesaPaymentService:
    """
    Centralized M-Pesa payment integration service.
    Provides STK Push initiation, status query, and webhook parsing.
    Used by finance.payment.services.PaymentOrchestrationService.
    """

    @classmethod
    def get_settings(cls):
        integration = Integrations.objects.filter(
            integration_type='PAYMENT',
            is_active=True,
            name='MPESA'
        ).first()
        if not integration:
            return None
        return MpesaSettings.objects.filter(integration=integration).first()

    @classmethod
    def initiate_stk_push(cls, phone, amount, account_reference, description="Payment"):
        # Use centralized config service for decryption and defaults
        config = IntegrationConfigService.get_mpesa_config(decrypt_secrets=True)
        if not config.get('consumer_key') or not config.get('consumer_secret') or not config.get('short_code'):
            return False, "Mpesa settings not configured", None
        consumer_key = config['consumer_key']
        consumer_secret = config['consumer_secret']
        passkey = config['passkey']

        try:
            # get token
            auth_resp = requests.get(
                f"{config['base_url']}/oauth/v1/generate?grant_type=client_credentials",
                auth=(consumer_key, consumer_secret),
                timeout=20,
            )
            auth_resp.raise_for_status()
            access_token = auth_resp.json().get('access_token')

            # password/timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            import base64
            pwd = base64.b64encode(f"{config['short_code']}{passkey}{timestamp}".encode()).decode()

            payload = {
                "BusinessShortCode": config['short_code'],
                "Password": pwd,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": int(Decimal(str(amount))),
                "PartyA": phone,
                "PartyB": config['short_code'],
                "PhoneNumber": phone,
                "CallBackURL": f"{config['callback_base_url']}",
                "AccountReference": account_reference,
                "TransactionDesc": description,
            }
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.post(f"{config['base_url']}/mpesa/stkpush/v1/processrequest", json=payload, headers=headers, timeout=30)
            data = resp.json()
            if resp.ok and data.get('ResponseCode') == '0':
                return True, "STK Push initiated", {
                    "checkout_id": data.get('CheckoutRequestID'),
                    "merchant_request_id": data.get('MerchantRequestID'),
                    "password": pwd,
                    "timestamp": timestamp,
                }
            return False, data.get('errorMessage') or 'Failed to initiate STK', data
        except Exception as e:
            logger.error(f"Mpesa STK initiation error: {str(e)}")
            return False, str(e), None

    @classmethod
    def query_stk_status(cls, checkout_id, password, timestamp):
        config = IntegrationConfigService.get_mpesa_config(decrypt_secrets=True)
        if not config.get('consumer_key') or not config.get('consumer_secret'):
            return False, "Mpesa settings not configured", None
        try:
            # token
            consumer_key = config['consumer_key']
            consumer_secret = config['consumer_secret']
            auth_resp = requests.get(
                f"{config['base_url']}/oauth/v1/generate?grant_type=client_credentials",
                auth=(consumer_key, consumer_secret),
                timeout=20,
            )
            access_token = auth_resp.json().get('access_token')
            payload = {
                "BusinessShortCode": config['short_code'],
                "Password": password,
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_id,
            }
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.post(f"{config['base_url']}/mpesa/stkpushquery/v1/query", json=payload, headers=headers, timeout=30)
            data = resp.json()
            return resp.ok, None if resp.ok else data.get('errorMessage'), data
        except Exception as e:
            logger.error(f"Mpesa STK query error: {str(e)}")
            return False, str(e), None


