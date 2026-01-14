"""
Paystack Payment Integration Service

Implements Paystack payment gateway integration for:
- Card payments
- Bank transfers
- Mobile money
- USSD payments

Documentation: https://paystack.com/docs/
"""

import hmac
import hashlib
import json
import logging
import requests
from decimal import Decimal
from typing import Optional, Dict, Any
from django.conf import settings

logger = logging.getLogger(__name__)


class PaystackPaymentService:
    """
    Service for processing payments via Paystack.

    Paystack is an African payment gateway supporting multiple payment methods
    and currencies (NGN, GHS, ZAR, KES, USD).
    """

    BASE_URL = 'https://api.paystack.co'

    @classmethod
    def get_settings(cls) -> Optional[Dict[str, Any]]:
        """
        Retrieve Paystack settings from database.

        Returns:
            dict: Paystack configuration settings or None if not configured
        """
        try:
            from integrations.models import PaystackSettings

            settings_obj = PaystackSettings.objects.first()
            if not settings_obj:
                logger.warning("Paystack settings not configured")
                return None

            return {
                'public_key': settings_obj.public_key,
                'secret_key': settings_obj.get_decrypted_secret_key(),
                'webhook_secret': settings_obj.get_decrypted_webhook_secret(),
                'base_url': settings_obj.base_url or cls.BASE_URL,
                'callback_url': settings_obj.callback_url,
                'webhook_url': settings_obj.webhook_url,
                'enabled_channels': settings_obj.enabled_channels,
                'default_currency': settings_obj.default_currency,
                'business_name': settings_obj.business_name,
                'support_email': settings_obj.support_email,
                'subaccount_code': settings_obj.subaccount_code,
                'is_test_mode': settings_obj.is_test_mode,
            }
        except Exception as e:
            logger.error(f"Error retrieving Paystack settings: {e}")
            return None

    @classmethod
    def initialize_transaction(
        cls,
        email: str,
        amount: Decimal,
        currency: str = 'KES',
        reference: Optional[str] = None,
        callback_url: Optional[str] = None,
        channels: Optional[list] = None,
        metadata: Optional[dict] = None,
        subaccount: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Initialize a Paystack transaction.

        Args:
            email: Customer email address
            amount: Amount in the currency's main unit (e.g., KES 100.00)
            currency: Currency code (NGN, GHS, ZAR, KES, USD)
            reference: Unique transaction reference (auto-generated if not provided)
            callback_url: URL to redirect after payment
            channels: Payment channels to display (card, bank, bank_transfer, ussd, qr, mobile_money)
            metadata: Custom data to attach to transaction
            subaccount: Subaccount code for split payments

        Returns:
            dict: {
                'success': bool,
                'authorization_url': str,  # URL to redirect customer for payment
                'access_code': str,
                'reference': str,
                'error': str (if failed)
            }
        """
        try:
            settings_data = cls.get_settings()
            if not settings_data:
                return {
                    'success': False,
                    'error': 'Paystack is not configured'
                }

            # Convert amount to kobo/pesewas (smallest currency unit)
            # Paystack expects amount in subunits
            amount_in_subunits = int(Decimal(str(amount)) * 100)

            # Build request payload
            payload = {
                'email': email,
                'amount': amount_in_subunits,
                'currency': currency or settings_data['default_currency'],
            }

            # Add optional parameters
            if reference:
                payload['reference'] = reference

            # Determine callback URL (priority: explicit > settings > auto-configured)
            if callback_url:
                payload['callback_url'] = callback_url
            elif settings_data.get('callback_url'):
                payload['callback_url'] = settings_data['callback_url']
            else:
                # Auto-configure from URL config service
                from integrations.services.url_config_service import URLConfigService
                payload['callback_url'] = URLConfigService.get_callback_url('paystack', 'callback')

            # Payment channels
            if channels:
                payload['channels'] = channels
            elif settings_data.get('enabled_channels'):
                payload['channels'] = settings_data['enabled_channels']

            # Metadata for tracking
            if metadata:
                payload['metadata'] = metadata

            # Split payments
            if subaccount or settings_data.get('subaccount_code'):
                payload['subaccount'] = subaccount or settings_data['subaccount_code']

            # Make API request
            headers = {
                'Authorization': f"Bearer {settings_data['secret_key']}",
                'Content-Type': 'application/json',
            }

            response = requests.post(
                f"{settings_data['base_url']}/transaction/initialize",
                json=payload,
                headers=headers,
                timeout=30
            )

            response_data = response.json()

            if response.status_code == 200 and response_data.get('status'):
                data = response_data.get('data', {})
                return {
                    'success': True,
                    'authorization_url': data.get('authorization_url'),
                    'access_code': data.get('access_code'),
                    'reference': data.get('reference'),
                }
            else:
                error_msg = response_data.get('message', 'Transaction initialization failed')
                logger.error(f"Paystack initialize error: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }

        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack request error: {e}")
            return {
                'success': False,
                'error': f'Network error: {str(e)}'
            }
        except Exception as e:
            logger.error(f"Paystack initialization error: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @classmethod
    def verify_transaction(cls, reference: str) -> Dict[str, Any]:
        """
        Verify a Paystack transaction status.

        Args:
            reference: Transaction reference from initialization

        Returns:
            dict: {
                'success': bool,
                'status': str,  # 'success', 'failed', 'pending', 'abandoned'
                'amount': Decimal,
                'currency': str,
                'channel': str,
                'reference': str,
                'gateway_response': str,
                'paid_at': str,
                'customer': dict,
                'authorization': dict,
                'error': str (if failed)
            }
        """
        try:
            settings_data = cls.get_settings()
            if not settings_data:
                return {
                    'success': False,
                    'error': 'Paystack is not configured'
                }

            headers = {
                'Authorization': f"Bearer {settings_data['secret_key']}",
            }

            response = requests.get(
                f"{settings_data['base_url']}/transaction/verify/{reference}",
                headers=headers,
                timeout=30
            )

            response_data = response.json()

            if response.status_code == 200 and response_data.get('status'):
                data = response_data.get('data', {})

                # Convert amount back from subunits
                amount = Decimal(str(data.get('amount', 0))) / 100

                return {
                    'success': True,
                    'status': data.get('status'),  # success, failed, etc.
                    'amount': amount,
                    'currency': data.get('currency'),
                    'channel': data.get('channel'),  # card, bank, etc.
                    'reference': data.get('reference'),
                    'gateway_response': data.get('gateway_response'),
                    'paid_at': data.get('paid_at'),
                    'customer': data.get('customer', {}),
                    'authorization': data.get('authorization', {}),
                    'metadata': data.get('metadata', {}),
                    'transaction_id': data.get('id'),
                }
            else:
                error_msg = response_data.get('message', 'Transaction verification failed')
                return {
                    'success': False,
                    'error': error_msg
                }

        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack verification request error: {e}")
            return {
                'success': False,
                'error': f'Network error: {str(e)}'
            }
        except Exception as e:
            logger.error(f"Paystack verification error: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @classmethod
    def verify_webhook_signature(cls, payload: bytes, signature: str) -> bool:
        """
        Verify Paystack webhook signature.

        Paystack signs webhook payloads using HMAC SHA512 with your secret key.

        Args:
            payload: Raw request body bytes
            signature: Value of x-paystack-signature header

        Returns:
            bool: True if signature is valid
        """
        try:
            settings_data = cls.get_settings()
            if not settings_data:
                logger.error("Cannot verify webhook: Paystack not configured")
                return False

            secret_key = settings_data['secret_key']
            if not secret_key:
                logger.error("Cannot verify webhook: Secret key not found")
                return False

            # Compute HMAC SHA512 hash
            computed_hash = hmac.new(
                secret_key.encode('utf-8'),
                payload,
                hashlib.sha512
            ).hexdigest()

            return hmac.compare_digest(computed_hash, signature)

        except Exception as e:
            logger.error(f"Webhook signature verification error: {e}")
            return False

    @classmethod
    def process_refund(
        cls,
        transaction_reference: str,
        amount: Optional[Decimal] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a refund for a completed transaction.

        Args:
            transaction_reference: Reference of the original transaction
            amount: Amount to refund (full refund if not specified)
            reason: Reason for the refund

        Returns:
            dict: {
                'success': bool,
                'refund_reference': str,
                'status': str,
                'error': str (if failed)
            }
        """
        try:
            settings_data = cls.get_settings()
            if not settings_data:
                return {
                    'success': False,
                    'error': 'Paystack is not configured'
                }

            payload = {
                'transaction': transaction_reference,
            }

            if amount:
                payload['amount'] = int(Decimal(str(amount)) * 100)

            if reason:
                payload['merchant_note'] = reason

            headers = {
                'Authorization': f"Bearer {settings_data['secret_key']}",
                'Content-Type': 'application/json',
            }

            response = requests.post(
                f"{settings_data['base_url']}/refund",
                json=payload,
                headers=headers,
                timeout=30
            )

            response_data = response.json()

            if response.status_code == 200 and response_data.get('status'):
                data = response_data.get('data', {})
                return {
                    'success': True,
                    'refund_reference': data.get('id'),
                    'status': data.get('status'),
                    'amount': Decimal(str(data.get('amount', 0))) / 100,
                }
            else:
                error_msg = response_data.get('message', 'Refund failed')
                return {
                    'success': False,
                    'error': error_msg
                }

        except Exception as e:
            logger.error(f"Paystack refund error: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @classmethod
    def list_banks(cls, country: str = 'kenya') -> Dict[str, Any]:
        """
        Get list of banks supported by Paystack for bank transfers.

        Args:
            country: Country code (nigeria, ghana, south-africa, kenya)

        Returns:
            dict: {
                'success': bool,
                'banks': list,
                'error': str (if failed)
            }
        """
        try:
            settings_data = cls.get_settings()
            if not settings_data:
                return {
                    'success': False,
                    'error': 'Paystack is not configured'
                }

            headers = {
                'Authorization': f"Bearer {settings_data['secret_key']}",
            }

            response = requests.get(
                f"{settings_data['base_url']}/bank",
                params={'country': country},
                headers=headers,
                timeout=30
            )

            response_data = response.json()

            if response.status_code == 200 and response_data.get('status'):
                return {
                    'success': True,
                    'banks': response_data.get('data', []),
                }
            else:
                return {
                    'success': False,
                    'error': response_data.get('message', 'Failed to fetch banks')
                }

        except Exception as e:
            logger.error(f"Paystack list banks error: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @classmethod
    def create_dedicated_account(
        cls,
        customer_email: str,
        customer_name: str,
        preferred_bank: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a dedicated virtual account for a customer.

        Args:
            customer_email: Customer email
            customer_name: Customer full name
            preferred_bank: Preferred bank for the virtual account

        Returns:
            dict: {
                'success': bool,
                'account_number': str,
                'bank_name': str,
                'customer_code': str,
                'error': str (if failed)
            }
        """
        try:
            settings_data = cls.get_settings()
            if not settings_data:
                return {
                    'success': False,
                    'error': 'Paystack is not configured'
                }

            headers = {
                'Authorization': f"Bearer {settings_data['secret_key']}",
                'Content-Type': 'application/json',
            }

            # First, create or get customer
            customer_payload = {
                'email': customer_email,
                'first_name': customer_name.split()[0] if customer_name else 'Customer',
                'last_name': ' '.join(customer_name.split()[1:]) if len(customer_name.split()) > 1 else '',
            }

            customer_response = requests.post(
                f"{settings_data['base_url']}/customer",
                json=customer_payload,
                headers=headers,
                timeout=30
            )

            if customer_response.status_code not in [200, 201]:
                return {
                    'success': False,
                    'error': 'Failed to create customer'
                }

            customer_data = customer_response.json().get('data', {})
            customer_code = customer_data.get('customer_code')

            # Create dedicated account
            account_payload = {
                'customer': customer_code,
            }

            if preferred_bank:
                account_payload['preferred_bank'] = preferred_bank

            account_response = requests.post(
                f"{settings_data['base_url']}/dedicated_account",
                json=account_payload,
                headers=headers,
                timeout=30
            )

            account_response_data = account_response.json()

            if account_response.status_code in [200, 201] and account_response_data.get('status'):
                data = account_response_data.get('data', {})
                return {
                    'success': True,
                    'account_number': data.get('account_number'),
                    'bank_name': data.get('bank', {}).get('name'),
                    'customer_code': customer_code,
                }
            else:
                return {
                    'success': False,
                    'error': account_response_data.get('message', 'Failed to create dedicated account')
                }

        except Exception as e:
            logger.error(f"Paystack dedicated account error: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @classmethod
    def get_transaction_totals(cls) -> Dict[str, Any]:
        """
        Get total amount received on the integration.

        Returns:
            dict: {
                'success': bool,
                'total_transactions': int,
                'total_volume': Decimal,
                'pending_transfers': Decimal,
                'error': str (if failed)
            }
        """
        try:
            settings_data = cls.get_settings()
            if not settings_data:
                return {
                    'success': False,
                    'error': 'Paystack is not configured'
                }

            headers = {
                'Authorization': f"Bearer {settings_data['secret_key']}",
            }

            response = requests.get(
                f"{settings_data['base_url']}/transaction/totals",
                headers=headers,
                timeout=30
            )

            response_data = response.json()

            if response.status_code == 200 and response_data.get('status'):
                data = response_data.get('data', {})
                return {
                    'success': True,
                    'total_transactions': data.get('total_transactions', 0),
                    'total_volume': Decimal(str(data.get('total_volume', 0))) / 100,
                    'pending_transfers': Decimal(str(data.get('pending_transfers', 0))) / 100,
                }
            else:
                return {
                    'success': False,
                    'error': response_data.get('message', 'Failed to fetch totals')
                }

        except Exception as e:
            logger.error(f"Paystack totals error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
