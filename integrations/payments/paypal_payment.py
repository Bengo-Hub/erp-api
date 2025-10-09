import requests
import json
import base64
import logging
from decimal import Decimal
from django.utils import timezone
import uuid
from ..models import Integrations
from ..utils import Crypto

logger = logging.getLogger(__name__)

# Default PayPal settings if database settings not available
DEFAULT_PAYPAL_BASE_URL = 'https://api-m.sandbox.paypal.com'
DEFAULT_PAYPAL_CLIENT_ID = 'your-client-id'
DEFAULT_PAYPAL_SECRET = 'your-secret'


class PayPalPaymentService:
    """
    Service for processing PayPal payments.
    This integrates with the central PaymentOrchestrationService.
    Uses settings from the PayPalSettings model.
    """
    
    @classmethod
    def get_settings(cls):
        """
        Get the PayPal settings from the database
        
        Returns:
            PayPalSettings: The active PayPal settings or None if not found
            dict: A dictionary with required PayPal config values
        """
        try:
            # Get the active payment integration
            integration = Integrations.objects.filter(
                integration_type='PAYMENT',
                is_active=True,
                paypal_settings__isnull=False
            ).first()
            
            if not integration:
                logger.warning("No active PayPal integration found. Using default values.")
                return None, {
                    'base_url': DEFAULT_PAYPAL_BASE_URL,
                    'client_id': DEFAULT_PAYPAL_CLIENT_ID,
                    'client_secret': DEFAULT_PAYPAL_SECRET,
                    'currency': 'KES',
                    'business_name': 'BengoERP',
                    'success_url': 'https://yourdomain.com/payment/success',
                    'cancel_url': 'https://yourdomain.com/payment/cancel',
                }
                
            settings = integration.paypal_settings.first()
            if not settings:
                logger.warning("PayPal integration found but no settings available. Using default values.")
                return None, {
                    'base_url': DEFAULT_PAYPAL_BASE_URL,
                    'client_id': DEFAULT_PAYPAL_CLIENT_ID,
                    'client_secret': DEFAULT_PAYPAL_SECRET,
                    'currency': 'KES',
                    'business_name': 'BengoERP',
                    'success_url': 'https://yourdomain.com/payment/success',
                    'cancel_url': 'https://yourdomain.com/payment/cancel',
                }
                
            # Decrypt sensitive values
            client_id = settings.client_id
            client_secret = settings.client_secret
            
            if "gAAAAA" in client_id:
                client_id = Crypto(client_id, 'decrypt').decrypt()
                
            if "gAAAAA" in client_secret:
                client_secret = Crypto(client_secret, 'decrypt').decrypt()
            
            # Return settings and config dictionary
            config = {
                'base_url': settings.base_url,
                'client_id': client_id,
                'client_secret': client_secret,
                'currency': settings.default_currency,
                'business_name': settings.business_name,
                'success_url': settings.success_url,
                'cancel_url': settings.cancel_url,
            }
            
            return settings, config
            
        except Exception as e:
            logger.error(f"Error retrieving PayPal settings: {str(e)}")
            return None, {
                'base_url': DEFAULT_PAYPAL_BASE_URL,
                'client_id': DEFAULT_PAYPAL_CLIENT_ID,
                'client_secret': DEFAULT_PAYPAL_SECRET,
                'currency': 'KES',
                'business_name': 'BengoERP',
                'success_url': 'https://yourdomain.com/payment/success',
                'cancel_url': 'https://yourdomain.com/payment/cancel',
            }

    @classmethod
    def get_access_token(cls):
        """
        Get an access token from PayPal for API authentication.
        
        Returns:
            str: PayPal access token or None on failure
        """
        try:
            # Get settings from database
            _, config = cls.get_settings()
            
            url = f"{config['base_url']}/v1/oauth2/token"
            
            # Create auth string (Basic auth with client ID and secret)
            auth_string = f"{config['client_id']}:{config['client_secret']}"
            encoded_auth = base64.b64encode(auth_string.encode()).decode()
            
            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            
            data = "grant_type=client_credentials"
            
            response = requests.post(url, headers=headers, data=data)
            
            if response.status_code == 200:
                return response.json().get("access_token")
            else:
                logger.error(f"Failed to get PayPal access token: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"PayPal access token error: {str(e)}")
            return None

    @classmethod
    def create_order(cls, amount, currency=None, order_items=None, customer_info=None, return_url=None, cancel_url=None):
        """
        Create a PayPal order.
        
        Args:
            amount (Decimal): Payment amount
            currency (str): Currency code (default from settings)
            order_items (list): List of order items
            customer_info (dict): Customer information
            return_url (str): URL to redirect after successful payment
            cancel_url (str): URL to redirect if payment is cancelled
            
        Returns:
            dict: Order creation result
        """
        try:
            # Get settings from database
            settings_obj, config = cls.get_settings()
            
            # Use settings from database or provided parameters
            currency = currency or config['currency']
            business_name = config['business_name']
            success_url = return_url or config['success_url']
            cancel_url = cancel_url or config['cancel_url']
            
            # Get access token for API call
            access_token = cls.get_access_token()
            if not access_token:
                return {
                    'success': False,
                    'message': 'Failed to get PayPal access token',
                }
            
            url = f"{config['base_url']}/v2/checkout/orders"
            
            # Set headers for the API request
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            
            # Prepare the order data
            payload = {
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "amount": {
                            "currency_code": currency,
                            "value": str(amount),
                        },
                        "reference_id": str(uuid.uuid4()),
                    }
                ],
                "application_context": {
                    "brand_name": business_name,
                    "return_url": success_url,
                    "cancel_url": cancel_url,
                    "user_action": "PAY_NOW",
                    "shipping_preference": "NO_SHIPPING",
                }
            }
            
            # Add order items if provided
            if order_items:
                payload["purchase_units"][0]["items"] = []
                for item in order_items:
                    payload["purchase_units"][0]["items"].append({
                        "name": item.get("name", "Product"),
                        "quantity": str(item.get("quantity", 1)),
                        "unit_amount": {
                            "currency_code": currency,
                            "value": str(item.get("price", 0)),
                        }
                    })
            
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            
            if response.status_code in (200, 201):
                data = response.json()
                
                # Extract the approval URL for the user to complete payment
                approval_url = next((link["href"] for link in data["links"] if link["rel"] == "approve"), None)
                
                return {
                    'success': True,
                    'order_id': data["id"],
                    'status': data["status"],
                    'approval_url': approval_url,
                    'timestamp': timezone.now().isoformat(),
                }
            else:
                logger.error(f"Failed to create PayPal order: {response.text}")
                return {
                    'success': False,
                    'error': f"Failed to create PayPal order: {response.text}",
                }
                
        except Exception as e:
            logger.error(f"PayPal order creation error: {str(e)}")
            return {
                'success': False,
                'error': 'An error occurred while creating the PayPal order',
                'detailed_error': str(e),
            }

    @classmethod
    def capture_payment(cls, order_id):
        """
        Capture an approved PayPal payment.
        
        Args:
            order_id (str): PayPal order ID to capture
            
        Returns:
            dict: Payment capture result
        """
        try:
            access_token = cls.get_access_token()
            
            if not access_token:
                return {
                    'success': False,
                    'error': 'Failed to authenticate with PayPal',
                }
            
            # Get settings from database
            _, config = cls.get_settings()
            
            url = f"{config['base_url']}/v2/checkout/orders/{order_id}/capture"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            
            response = requests.post(url, headers=headers)
            
            if response.status_code in (200, 201):
                data = response.json()
                capture_id = data["purchase_units"][0]["payments"]["captures"][0]["id"]
                capture_status = data["purchase_units"][0]["payments"]["captures"][0]["status"]
                amount = data["purchase_units"][0]["payments"]["captures"][0]["amount"]["value"]
                currency = data["purchase_units"][0]["payments"]["captures"][0]["amount"]["currency_code"]
                
                return {
                    'success': True,
                    'transaction_id': capture_id,
                    'order_id': order_id,
                    'status': capture_status,
                    'amount': Decimal(amount),
                    'currency': currency,
                    'payment_method': 'paypal',
                    'timestamp': timezone.now().isoformat(),
                }
            else:
                logger.error(f"Failed to capture PayPal payment: {response.text}")
                return {
                    'success': False,
                    'error': f"Failed to capture payment: {response.text}",
                }
                
        except Exception as e:
            logger.error(f"PayPal payment capture error: {str(e)}")
            return {
                'success': False,
                'error': 'An error occurred while capturing the PayPal payment',
                'detailed_error': str(e),
            }

    @classmethod
    def verify_payment(cls, order_id):
        """
        Verify a PayPal payment status.
        
        Args:
            order_id (str): PayPal order ID
            
        Returns:
            dict: Payment verification result
        """
        try:
            access_token = cls.get_access_token()
            
            if not access_token:
                return {
                    'success': False,
                    'error': 'Failed to authenticate with PayPal',
                }
            
            # Get settings from database
            _, config = cls.get_settings()
            
            url = f"{config['base_url']}/v2/checkout/orders/{order_id}"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'order_id': data["id"],
                    'status': data["status"],
                    'amount': Decimal(data["purchase_units"][0]["amount"]["value"]),
                    'currency': data["purchase_units"][0]["amount"]["currency_code"],
                }
            else:
                logger.error(f"Failed to verify PayPal payment: {response.text}")
                return {
                    'success': False,
                    'error': f"Failed to verify payment: {response.text}",
                }
                
        except Exception as e:
            logger.error(f"PayPal payment verification error: {str(e)}")
            return {
                'success': False,
                'error': 'An error occurred while verifying the PayPal payment',
                'detailed_error': str(e),
            }

    @classmethod
    def process_refund(cls, capture_id, amount=None, reason=None):
        """
        Process a refund for a PayPal payment.
        
        Args:
            capture_id (str): PayPal capture ID to refund
            amount (Decimal, optional): Amount to refund (default: full amount)
            reason (str, optional): Reason for the refund
            
        Returns:
            dict: Refund processing result
        """
        try:
            access_token = cls.get_access_token()
            
            if not access_token:
                return {
                    'success': False,
                    'error': 'Failed to authenticate with PayPal',
                }
            
            # Get settings from database
            _, config = cls.get_settings()
            
            url = f"{config['base_url']}/v2/payments/captures/{capture_id}/refund"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            
            # Prepare refund data
            payload = {}
            
            if amount:
                # Get currency from settings or use default
                payload["amount"] = {
                    "value": str(amount),
                    "currency_code": config['currency'],
                }
                
            if reason:
                payload["note_to_payer"] = reason
                
            response = requests.post(url, headers=headers, data=json.dumps(payload) if payload else "")
            
            if response.status_code in (200, 201):
                data = response.json()
                return {
                    'success': True,
                    'refund_id': data["id"],
                    'status': data["status"],
                    'amount': Decimal(data["amount"]["value"]),
                    'currency': data["amount"]["currency_code"],
                    'transaction_id': capture_id,
                }
            else:
                logger.error(f"Failed to process PayPal refund: {response.text}")
                return {
                    'success': False,
                    'error': f"Failed to process refund: {response.text}",
                }
                
        except Exception as e:
            logger.error(f"PayPal refund processing error: {str(e)}")
            return {
                'success': False,
                'error': 'An error occurred while processing the PayPal refund',
                'detailed_error': str(e),
            }
