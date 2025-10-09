from django.conf import settings
import stripe
import logging
from decimal import Decimal
from django.utils import timezone
from ..models import Integrations
from ..utils import Crypto

logger = logging.getLogger(__name__)

# Configure stripe with default settings in case no settings found in DB
DEFAULT_STRIPE_KEY = getattr(settings, 'STRIPE_SECRET_KEY', 'sk_test_yourkeyhere')
stripe.api_key = DEFAULT_STRIPE_KEY


class CardPaymentService:
    """
    Service for processing card payments using Stripe.
    This integrates with the central PaymentOrchestrationService.
    Uses settings from the CardPaymentSettings model.
    """

    @classmethod
    def get_settings(cls):
        """
        Get the card payment settings from the database
        
        Returns:
            CardPaymentSettings: The active card payment settings or None if not found
        """
        try:
            # Get the active payment integration
            integration = Integrations.objects.filter(
                integration_type='PAYMENT',
                is_active=True,
                card_payment_settings__isnull=False
            ).first()
            
            if not integration:
                return None
                
            settings = integration.card_payment_settings.first()
            if settings:
                # Decrypt the API key
                if "gAAAAA" in settings.api_key:
                    api_key = Crypto(settings.api_key, 'decrypt').decrypt()
                else:
                    api_key = settings.api_key
                    
                # Set the API key for Stripe
                stripe.api_key = api_key
                    
                return settings
            return None
        except Exception as e:
            logger.error(f"Error retrieving card payment settings: {str(e)}")
            return None
    
    @classmethod
    def process_payment(cls, amount, currency=None, card_details=None, metadata=None, description=None):
        """
        Process a card payment through Stripe.
        
        Args:
            amount (Decimal): Payment amount
            currency (str): Currency code (default: KES)
            card_details (dict): Card details from the payment form
            metadata (dict): Additional data to store with the payment
            description (str): Description of the payment
            
        Returns:
            dict: Payment processing result
        """
        try:
            # Get settings from database
            settings = cls.get_settings()
            
            # Use settings from database or fall back to defaults
            if settings:
                currency = currency or settings.default_currency
                description = description or f"{settings.business_name} Purchase"
                return_url = settings.success_url
            else:
                # Use defaults if no settings found
                currency = currency or 'KES'
                description = description or 'BengoERP Purchase'
                return_url = 'https://yourdomain.com/payment/success'
            
            # Convert decimal amount to cents/smallest currency unit for Stripe
            amount_in_cents = int(amount * 100)
            
            # Create a payment method from the card details
            payment_method = stripe.PaymentMethod.create(
                type='card',
                card={
                    'number': card_details.get('cardNumber'),
                    'exp_month': int(card_details.get('expiryMonth')),
                    'exp_year': int(card_details.get('expiryYear')),
                    'cvc': card_details.get('cvv'),
                },
                billing_details={
                    'name': card_details.get('cardholderName'),
                }
            )
            
            # Add business details if available
            payment_options = {}
            if settings and settings.statement_descriptor:
                payment_options['statement_descriptor'] = settings.statement_descriptor[:22]  # Stripe limit
            
            # Create a payment intent
            payment_intent = stripe.PaymentIntent.create(
                amount=amount_in_cents,
                currency=currency.lower(),
                payment_method=payment_method.id,
                confirm=True,
                description=description,
                metadata=metadata or {},
                return_url=return_url,  # For 3D Secure redirects
                **payment_options
            )
            
            # Handle the payment result
            if payment_intent.status == 'succeeded':
                return {
                    'success': True,
                    'transaction_id': payment_intent.id,
                    'amount': amount,
                    'currency': currency,
                    'payment_method': 'card',
                    'status': payment_intent.status,
                    'timestamp': timezone.now().isoformat(),
                    'customer_name': card_details.get('cardholderName'),
                    'card_last4': payment_method.card.last4,
                    'card_brand': payment_method.card.brand,
                }
            elif payment_intent.status == 'requires_action':
                # 3D Secure authentication required
                return {
                    'success': False,
                    'requires_action': True,
                    'client_secret': payment_intent.client_secret,
                    'transaction_id': payment_intent.id,
                }
            else:
                return {
                    'success': False,
                    'error': f'Payment failed with status: {payment_intent.status}',
                    'transaction_id': payment_intent.id,
                }
                
        except stripe.error.CardError as e:
            # Card declined
            error_message = e.error.message
            logger.error(f"Card payment error: {error_message}")
            return {
                'success': False,
                'error': error_message,
                'error_code': e.error.code,
            }
            
        except (stripe.error.StripeError, Exception) as e:
            # Other Stripe errors or unexpected errors
            error_message = str(e)
            logger.error(f"Stripe payment processing error: {error_message}")
            return {
                'success': False,
                'error': 'An error occurred while processing your payment. Please try again.',
                'detailed_error': error_message,
            }

    @classmethod
    def verify_payment(cls, transaction_id):
        """
        Verify a payment status.
        
        Args:
            transaction_id (str): Stripe payment intent ID
            
        Returns:
            dict: Payment verification result
        """
        try:
            payment_intent = stripe.PaymentIntent.retrieve(transaction_id)
            
            return {
                'success': payment_intent.status == 'succeeded',
                'status': payment_intent.status,
                'transaction_id': payment_intent.id,
                'amount': Decimal(payment_intent.amount) / 100,  # Convert cents back to decimal
                'currency': payment_intent.currency.upper(),
            }
            
        except Exception as e:
            logger.error(f"Payment verification error: {str(e)}")
            return {
                'success': False,
                'error': 'Failed to verify payment status',
                'detailed_error': str(e),
            }

    @classmethod
    def process_refund(cls, transaction_id, amount=None, reason=None):
        """
        Process a refund for a payment.
        
        Args:
            transaction_id (str): Stripe payment intent ID
            amount (Decimal, optional): Amount to refund (default: full amount)
            reason (str, optional): Reason for the refund
            
        Returns:
            dict: Refund processing result
        """
        try:
            refund_params = {
                'payment_intent': transaction_id,
                'reason': reason or 'requested_by_customer',
            }
            
            if amount:
                refund_params['amount'] = int(amount * 100)
                
            refund = stripe.Refund.create(**refund_params)
            
            return {
                'success': True,
                'refund_id': refund.id,
                'status': refund.status,
                'amount': Decimal(refund.amount) / 100 if refund.amount else None,
                'currency': refund.currency.upper() if refund.currency else None,
                'transaction_id': transaction_id,
            }
            
        except Exception as e:
            logger.error(f"Refund processing error: {str(e)}")
            return {
                'success': False,
                'error': 'Failed to process refund',
                'detailed_error': str(e),
            }
