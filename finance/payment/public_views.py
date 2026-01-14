"""
Public Payment Views

Handles payment processing for public invoice/document pages.
Allows unauthenticated payment for shared documents.
"""

import json
import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.response import APIResponse
from .services import PaymentOrchestrationService

logger = logging.getLogger(__name__)


class PublicInvoicePaymentView(APIView):
    """
    Public endpoint for processing payments on shared invoices.
    Supports multiple payment methods: M-Pesa, Paystack, Card, PayPal.
    """
    permission_classes = [AllowAny]

    def post(self, request, invoice_id, token):
        """
        Initialize payment for a public invoice.

        Request body:
        {
            "payment_method": "paystack" | "mpesa" | "card" | "paypal",
            "amount": 1000.00,
            "email": "customer@example.com",
            "phone": "254712345678",  # Required for M-Pesa
            "callback_url": "https://...",  # Optional
            "customer_name": "John Doe"  # Optional
        }

        Returns:
            - For redirect-based payments (Paystack, PayPal): authorization_url
            - For STK push (M-Pesa): checkout_request_id
        """
        try:
            from finance.invoicing.models import Invoice

            # Validate invoice and token
            try:
                invoice = Invoice.objects.get(
                    id=invoice_id,
                    share_token=token,
                    is_shared=True
                )
            except Invoice.DoesNotExist:
                return APIResponse.error(
                    error_code='INVOICE_NOT_FOUND',
                    message='Invoice not found or access denied',
                    status_code=status.HTTP_404_NOT_FOUND
                )

            # Check if public payment is allowed
            if not invoice.allow_public_payment:
                return APIResponse.error(
                    error_code='PAYMENT_NOT_ALLOWED',
                    message='Public payment is not enabled for this invoice',
                    status_code=status.HTTP_403_FORBIDDEN
                )

            # Check if invoice is already paid
            if invoice.status == 'paid' or invoice.balance_due <= 0:
                return APIResponse.error(
                    error_code='ALREADY_PAID',
                    message='This invoice has already been paid',
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Extract payment details
            payment_method = request.data.get('payment_method', '').lower()
            amount = Decimal(str(request.data.get('amount', invoice.balance_due)))
            email = request.data.get('email') or invoice.customer.user.email if invoice.customer and invoice.customer.user else None
            phone = request.data.get('phone') or (invoice.customer.user.phone if invoice.customer and invoice.customer.user else None)
            callback_url = request.data.get('callback_url')
            customer_name = request.data.get('customer_name', '')

            # Validate amount
            if amount <= 0 or amount > invoice.balance_due:
                return APIResponse.error(
                    error_code='INVALID_AMOUNT',
                    message=f'Amount must be between 0 and {invoice.balance_due}',
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Generate unique reference
            import uuid
            reference = f"INV-{invoice.invoice_number}-{uuid.uuid4().hex[:8]}"

            # Route to appropriate payment processor
            if payment_method == 'paystack':
                return self._process_paystack_payment(
                    invoice, amount, email, reference, callback_url, customer_name
                )
            elif payment_method == 'mpesa':
                return self._process_mpesa_payment(
                    invoice, amount, phone, reference
                )
            elif payment_method == 'card':
                return self._process_card_payment(
                    invoice, amount, email, reference, customer_name
                )
            elif payment_method == 'paypal':
                return self._process_paypal_payment(
                    invoice, amount, email, reference, callback_url
                )
            else:
                return APIResponse.error(
                    error_code='INVALID_PAYMENT_METHOD',
                    message='Supported methods: paystack, mpesa, card, paypal',
                    status_code=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"Public invoice payment error: {e}", exc_info=True)
            return APIResponse.error(
                error_code='PAYMENT_ERROR',
                message=str(e),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _process_paystack_payment(self, invoice, amount, email, reference, callback_url, customer_name):
        """Process payment via Paystack."""
        if not email:
            return APIResponse.error(
                error_code='EMAIL_REQUIRED',
                message='Email is required for Paystack payments',
                status_code=status.HTTP_400_BAD_REQUEST
            )

        from integrations.payments.paystack_payment import PaystackPaymentService

        result = PaystackPaymentService.initialize_transaction(
            email=email,
            amount=amount,
            currency=invoice.currency or 'KES',
            reference=reference,
            callback_url=callback_url,
            metadata={
                'invoice_id': invoice.id,
                'invoice_number': invoice.invoice_number,
                'customer_name': customer_name,
                'payment_type': 'invoice',
            }
        )

        if result.get('success'):
            return APIResponse.success(
                data={
                    'payment_method': 'paystack',
                    'authorization_url': result.get('authorization_url'),
                    'access_code': result.get('access_code'),
                    'reference': result.get('reference'),
                },
                message='Payment initialized. Redirect to authorization URL.'
            )
        else:
            return APIResponse.error(
                error_code='PAYSTACK_ERROR',
                message=result.get('error', 'Failed to initialize Paystack payment'),
                status_code=status.HTTP_400_BAD_REQUEST
            )

    def _process_mpesa_payment(self, invoice, amount, phone, reference):
        """Process payment via M-Pesa STK Push."""
        if not phone:
            return APIResponse.error(
                error_code='PHONE_REQUIRED',
                message='Phone number is required for M-Pesa payments',
                status_code=status.HTTP_400_BAD_REQUEST
            )

        from integrations.payments.mpesa_payment import MpesaPaymentService

        # MpesaPaymentService.initiate_stk_push returns tuple: (success, message, data)
        success, message, data = MpesaPaymentService.initiate_stk_push(
            phone=phone,
            amount=int(amount),
            account_reference=invoice.invoice_number,
            description=f"Payment for Invoice {invoice.invoice_number}"
        )

        if success and data:
            return APIResponse.success(
                data={
                    'payment_method': 'mpesa',
                    'checkout_request_id': data.get('checkout_id'),
                    'merchant_request_id': data.get('merchant_request_id'),
                    'reference': reference,
                },
                message='M-Pesa prompt sent. Enter your PIN to complete payment.'
            )
        else:
            return APIResponse.error(
                error_code='MPESA_ERROR',
                message=message or 'Failed to initiate M-Pesa payment',
                status_code=status.HTTP_400_BAD_REQUEST
            )

    def _process_card_payment(self, invoice, amount, email, reference, customer_name):
        """Process payment via Card (Stripe)."""
        if not email:
            return APIResponse.error(
                error_code='EMAIL_REQUIRED',
                message='Email is required for card payments',
                status_code=status.HTTP_400_BAD_REQUEST
            )

        from integrations.payments.card_payment import CardPaymentService

        result = CardPaymentService.process_payment(
            amount=amount,
            currency=invoice.currency or 'KES',
            card_details={'email': email, 'name': customer_name},
            metadata={
                'invoice_id': invoice.id,
                'invoice_number': invoice.invoice_number,
            },
            description=f"Payment for Invoice {invoice.invoice_number}"
        )

        if result.get('success'):
            return APIResponse.success(
                data={
                    'payment_method': 'card',
                    'client_secret': result.get('client_secret'),
                    'payment_intent_id': result.get('payment_intent_id'),
                    'reference': reference,
                },
                message='Card payment initialized.'
            )
        else:
            return APIResponse.error(
                error_code='CARD_ERROR',
                message=result.get('error', 'Failed to process card payment'),
                status_code=status.HTTP_400_BAD_REQUEST
            )

    def _process_paypal_payment(self, invoice, amount, email, reference, callback_url):
        """Process payment via PayPal."""
        from integrations.payments.paypal_payment import PayPalPaymentService

        result = PayPalPaymentService.create_order(
            amount=amount,
            currency=invoice.currency or 'KES',
            order_items=[{
                'name': f"Invoice {invoice.invoice_number}",
                'quantity': 1,
                'unit_amount': float(amount),
            }],
            customer_info={'email': email} if email else None,
            return_url=callback_url,
            cancel_url=callback_url,
        )

        if result.get('success'):
            return APIResponse.success(
                data={
                    'payment_method': 'paypal',
                    'order_id': result.get('order_id'),
                    'approval_url': result.get('approval_url'),
                    'reference': reference,
                },
                message='PayPal order created. Redirect to approval URL.'
            )
        else:
            return APIResponse.error(
                error_code='PAYPAL_ERROR',
                message=result.get('error', 'Failed to create PayPal order'),
                status_code=status.HTTP_400_BAD_REQUEST
            )


class PaystackWebhookView(APIView):
    """
    Handle Paystack webhook callbacks.
    Verifies webhook signature and processes payment events.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """Process Paystack webhook events."""
        try:
            from integrations.payments.paystack_payment import PaystackPaymentService
            from finance.invoicing.models import Invoice

            # Get signature from header
            signature = request.headers.get('x-paystack-signature', '')

            # Verify webhook signature
            raw_body = request.body
            if not PaystackPaymentService.verify_webhook_signature(raw_body, signature):
                logger.warning("Invalid Paystack webhook signature")
                return Response({'status': 'invalid_signature'}, status=status.HTTP_400_BAD_REQUEST)

            # Parse event data
            event_data = request.data
            event_type = event_data.get('event')
            data = event_data.get('data', {})

            logger.info(f"Paystack webhook received: {event_type}")

            # Handle charge.success event
            if event_type == 'charge.success':
                reference = data.get('reference')
                amount = Decimal(str(data.get('amount', 0))) / 100  # Convert from kobo
                metadata = data.get('metadata', {})
                invoice_id = metadata.get('invoice_id')

                if invoice_id:
                    try:
                        invoice = Invoice.objects.get(id=invoice_id)

                        # Record the payment
                        with transaction.atomic():
                            invoice.record_payment(
                                amount=amount,
                                payment_method='paystack',
                                payment_reference=reference,
                                payment_date=timezone.now().date()
                            )

                        logger.info(f"Paystack payment recorded for invoice {invoice.invoice_number}")

                    except Invoice.DoesNotExist:
                        logger.warning(f"Invoice not found for Paystack payment: {invoice_id}")
                    except Exception as e:
                        logger.error(f"Error recording Paystack payment: {e}")

            return Response({'status': 'success'}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Paystack webhook error: {e}", exc_info=True)
            return Response({'status': 'error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PaystackVerifyPaymentView(APIView):
    """
    Verify Paystack payment status.
    Can be called by frontend after payment redirect.
    """
    permission_classes = [AllowAny]

    def get(self, request, reference):
        """
        Verify a Paystack transaction by reference.

        Returns payment status and updates invoice if successful.
        """
        try:
            from integrations.payments.paystack_payment import PaystackPaymentService
            from finance.invoicing.models import Invoice

            result = PaystackPaymentService.verify_transaction(reference)

            if not result.get('success'):
                return APIResponse.error(
                    error_code='VERIFICATION_FAILED',
                    message=result.get('error', 'Payment verification failed'),
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            payment_status = result.get('status')
            metadata = result.get('metadata', {})
            invoice_id = metadata.get('invoice_id')

            # If payment successful and invoice found, record payment
            if payment_status == 'success' and invoice_id:
                try:
                    invoice = Invoice.objects.get(id=invoice_id)

                    # Only record if not already recorded (idempotency)
                    existing_payment = invoice.payments.filter(reference=reference).exists()
                    if not existing_payment:
                        with transaction.atomic():
                            invoice.record_payment(
                                amount=result.get('amount'),
                                payment_method='paystack',
                                payment_reference=reference,
                                payment_date=timezone.now().date()
                            )

                except Invoice.DoesNotExist:
                    pass

            # Build response data
            response_data = {
                'status': payment_status,
                'amount': float(result.get('amount', 0)),
                'currency': result.get('currency'),
                'reference': result.get('reference'),
                'channel': result.get('channel'),
                'paid_at': result.get('paid_at'),
            }

            # Add invoice info if available
            if invoice_id:
                try:
                    invoice = Invoice.objects.get(id=invoice_id)
                    response_data['invoice_id'] = invoice.id
                    response_data['invoice_number'] = invoice.invoice_number
                    response_data['invoice_token'] = invoice.share_token
                except Invoice.DoesNotExist:
                    pass

            return APIResponse.success(
                data=response_data,
                message='Payment verified successfully' if payment_status == 'success' else f'Payment status: {payment_status}'
            )

        except Exception as e:
            logger.error(f"Paystack verification error: {e}", exc_info=True)
            return APIResponse.error(
                error_code='VERIFICATION_ERROR',
                message=str(e),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PublicPaymentMethodsView(APIView):
    """
    Get available payment methods for public invoice payments.
    Returns configured and active payment gateways.
    """
    permission_classes = [AllowAny]

    def get(self, request, invoice_id, token):
        """
        Get available payment methods for a public invoice.
        """
        try:
            from finance.invoicing.models import Invoice
            from integrations.models import MpesaSettings, PaystackSettings
            # Import optional payment settings (may not exist)
            try:
                from integrations.models import CardPaymentSettings, PayPalSettings
            except ImportError:
                CardPaymentSettings = None
                PayPalSettings = None

            # Validate invoice and token
            try:
                invoice = Invoice.objects.get(
                    id=invoice_id,
                    share_token=token,
                    is_shared=True
                )
            except Invoice.DoesNotExist:
                return APIResponse.error(
                    error_code='INVOICE_NOT_FOUND',
                    message='Invoice not found or access denied',
                    status_code=status.HTTP_404_NOT_FOUND
                )

            methods = []

            # Check M-Pesa availability
            mpesa_settings = MpesaSettings.objects.first()
            mpesa_enabled = bool(mpesa_settings and mpesa_settings.short_code)
            methods.append({
                'method': 'mpesa',
                'name': 'M-Pesa',
                'description': 'Pay via M-Pesa mobile money',
                'enabled': mpesa_enabled,
            })

            # Check Paystack availability
            paystack_settings = PaystackSettings.objects.first()
            paystack_enabled = bool(paystack_settings and paystack_settings.public_key)
            methods.append({
                'method': 'paystack',
                'name': 'Paystack',
                'description': 'Pay with card, bank transfer, or mobile money',
                'enabled': paystack_enabled,
            })

            # Check Card/Stripe availability
            card_enabled = False
            if CardPaymentSettings:
                try:
                    card_settings = CardPaymentSettings.objects.first()
                    card_enabled = bool(card_settings and card_settings.public_key)
                except Exception:
                    pass
            methods.append({
                'method': 'card',
                'name': 'Credit/Debit Card',
                'description': 'Pay with Visa, Mastercard, or other cards',
                'enabled': card_enabled,
            })

            # Check PayPal availability
            paypal_enabled = False
            if PayPalSettings:
                try:
                    paypal_settings = PayPalSettings.objects.first()
                    paypal_enabled = bool(paypal_settings and paypal_settings.client_id)
                except Exception:
                    pass
            methods.append({
                'method': 'paypal',
                'name': 'PayPal',
                'description': 'Pay with your PayPal account',
                'enabled': paypal_enabled,
            })

            return APIResponse.success(
                data={
                    'invoice_number': invoice.invoice_number,
                    'amount_due': float(invoice.balance_due),
                    'currency': invoice.currency or 'KES',
                    'allow_public_payment': invoice.allow_public_payment,
                    'methods': methods,
                },
                message='Payment methods retrieved successfully'
            )

        except Exception as e:
            logger.error(f"Error getting payment methods: {e}", exc_info=True)
            return APIResponse.error(
                error_code='ERROR',
                message=str(e),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
