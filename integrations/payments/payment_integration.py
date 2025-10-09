import logging
from .card_payment import CardPaymentService
from .paypal_payment import PayPalPaymentService

logger = logging.getLogger(__name__)

class PaymentIntegrationManager:
    """
    Integration manager that connects external payment providers to the
    centralized PaymentOrchestrationService in the finance module.
    
    This acts as a bridge between payment providers (Stripe, PayPal) and
    the internal payment orchestration system.
    """
    
    @staticmethod
    def process_payment(payment_method, amount, currency='KES', payment_details=None, order_data=None):
        """
        Process a payment using the specified payment method
        
        Args:
            payment_method (str): Payment method ('card', 'paypal', etc.)
            amount (Decimal): Payment amount
            currency (str): Currency code (default: KES)
            payment_details (dict): Payment method specific details
            order_data (dict): Order information
            
        Returns:
            dict: Payment processing result
        """
        logger.info(f"Processing {payment_method} payment for {amount} {currency}")
        
        # Route to the appropriate payment processor based on the method
        if payment_method == 'card':
            return CardPaymentService.process_payment(
                amount=amount,
                currency=currency,
                card_details=payment_details,
                metadata=order_data,
                description=f"Order {order_data.get('order_id')}" if order_data else None
            )
            
        elif payment_method == 'paypal':
            # For PayPal, we first create an order, then the frontend will redirect for approval
            return PayPalPaymentService.create_order(
                amount=amount,
                currency=currency,
                order_items=order_data.get('items'),
                customer_info=order_data.get('customer'),
                return_url=order_data.get('return_url'),
                cancel_url=order_data.get('cancel_url')
            )
            
        # Add other payment methods as needed
        
        return {
            'success': False,
            'error': f'Unsupported payment method: {payment_method}'
        }
    
    @staticmethod
    def verify_payment(payment_method, transaction_id):
        """
        Verify a payment status
        
        Args:
            payment_method (str): Payment method ('card', 'paypal', etc.)
            transaction_id (str): Transaction ID to verify
            
        Returns:
            dict: Payment verification result
        """
        logger.info(f"Verifying {payment_method} payment {transaction_id}")
        
        if payment_method == 'card':
            return CardPaymentService.verify_payment(transaction_id)
            
        elif payment_method == 'paypal':
            return PayPalPaymentService.verify_payment(transaction_id)
            
        return {
            'success': False,
            'error': f'Unsupported payment method: {payment_method}'
        }
    
    @staticmethod
    def process_refund(payment_method, transaction_id, amount=None, reason=None):
        """
        Process a refund
        
        Args:
            payment_method (str): Payment method ('card', 'paypal', etc.)
            transaction_id (str): Transaction ID to refund
            amount (Decimal, optional): Amount to refund (default: full amount)
            reason (str, optional): Reason for the refund
            
        Returns:
            dict: Refund processing result
        """
        logger.info(f"Processing refund for {payment_method} payment {transaction_id}")
        
        if payment_method == 'card':
            return CardPaymentService.process_refund(
                transaction_id=transaction_id,
                amount=amount,
                reason=reason
            )
            
        elif payment_method == 'paypal':
            return PayPalPaymentService.process_refund(
                capture_id=transaction_id,
                amount=amount,
                reason=reason
            )
            
        return {
            'success': False,
            'error': f'Unsupported payment method: {payment_method}'
        }
        
    @staticmethod
    def capture_paypal_payment(order_id):
        """
        Capture an approved PayPal payment
        
        Args:
            order_id (str): PayPal order ID to capture
            
        Returns:
            dict: Payment capture result
        """
        logger.info(f"Capturing PayPal payment for order {order_id}")
        return PayPalPaymentService.capture_payment(order_id)
