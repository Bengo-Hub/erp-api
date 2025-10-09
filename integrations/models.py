from django.db import models
from .utils import Crypto
from datetime import time as _time
from decimal import Decimal as _Decimal

# Integration Type Choices
INTEGRATION_TYPES = [
    ('PAYMENT', 'Payment Integration'),
]
AVAILABLE_PAYMENT_INTEGRATIONS = [
    ('MPESA', 'Mpesa'),
    ('PAYPAL', 'PayPal'),
    ('CARD', 'Card Payment'),
]
# SMS Provider Choices
SMS_PROVIDERS = [
    ('TWILIO', 'Twilio'),
    ('AFRICASTALKING', 'Africa\'s Talking'),
    ('NEXMO', 'Nexmo/Vonage'),
    ('AWS_SNS', 'AWS SNS'),
]

class Integrations(models.Model):
    """Base model for all integration types"""
    name = models.CharField(max_length=100,choices=AVAILABLE_PAYMENT_INTEGRATIONS,default='MPESA')
    integration_type = models.CharField(max_length=20, choices=INTEGRATION_TYPES)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.integration_type})"
    
    def save(self, *args, **kwargs):
        # If this integration is set as default, unset any other defaults of the same type
        if self.is_default:
            Integrations.objects.filter(
                integration_type=self.integration_type, 
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name_plural = "Integrations"
        ordering = ['integration_type', '-is_default', 'name']

# EmailConfig moved to centralized notifications app
# Use: from notifications.models import EmailConfiguration

# Payment Provider Choices
PAYMENT_PROVIDERS = [
    ('MPESA', 'M-Pesa'),
    ('CARD', 'Credit/Debit Card'),
    ('PAYPAL', 'PayPal'),
    ('BANK', 'Bank Transfer'),
]

class MpesaSettings(models.Model):
    integration = models.ForeignKey(
        Integrations,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='mpesa_settings',
        limit_choices_to={'integration_type': 'PAYMENT'}
    )
    consumer_secret = models.CharField(max_length=1500, default='consumer secret')
    consumer_key = models.CharField(max_length=1500, default='consumer key')
    passkey = models.CharField(max_length=1500, default="passkey")
    security_credential = models.CharField(max_length=1500, default='credential')
    short_code = models.CharField(max_length=100, default='4133621')
    base_url = models.URLField(default='https://api.safaricom.co.ke')
    callback_base_url = models.URLField(default='https://posapi.kwaboi.co.ke/api/callback/')
    initiator_name = models.CharField(max_length=1500, default='towuor')
    initiator_password = models.CharField(max_length=255, default='@Yogis202402$')

    def save(self, *args, **kwargs):
        if "gAAAAA" not in self.consumer_key:
            self.consumer_key = Crypto(self.consumer_key, 'encrypt').encrypt()
        if "gAAAAA" not in self.consumer_secret:
            self.consumer_secret = Crypto(self.consumer_secret, 'encrypt').encrypt()
            self.passkey = Crypto(self.passkey, 'encrypt').encrypt()
        if "gAAAAA" not in self.security_credential:
            self.security_credential = Crypto(self.security_credential, 'encrypt').encrypt()
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"M-Pesa Settings - {self.short_code}"
    
    class Meta:
        verbose_name = "M-Pesa Settings"
        verbose_name_plural = "M-Pesa Settings"

class CardPaymentSettings(models.Model):
    """Settings for credit/debit card payment processing"""
    integration = models.ForeignKey(
        Integrations,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='card_payment_settings',
        limit_choices_to={'integration_type': 'PAYMENT'}
    )
    # Provider info (Stripe, etc)
    provider = models.CharField(max_length=50, default='STRIPE', help_text="Payment processor name")
    is_test_mode = models.BooleanField(default=True, help_text="Use test/sandbox environment")
    
    # API credentials
    api_key = models.CharField(max_length=1500, default='sk_test_your_stripe_key')
    public_key = models.CharField(max_length=1500, default='pk_test_your_stripe_key', help_text="Public/publishable key")
    webhook_secret = models.CharField(max_length=1500, blank=True, null=True)
    
    # Configuration
    base_url = models.URLField(default='https://api.stripe.com', help_text="API base URL")
    webhook_url = models.URLField(default='https://yourdomain.com/api/payments/stripe/webhook', help_text="URL for payment webhooks")
    success_url = models.URLField(default='https://yourdomain.com/payment/success')
    cancel_url = models.URLField(default='https://yourdomain.com/payment/cancel')
    
    # Currency and business settings
    default_currency = models.CharField(max_length=3, default='KES')
    business_name = models.CharField(max_length=255, default='BengoERP')
    statement_descriptor = models.CharField(max_length=22, default='BengoERP Purchase', help_text="Text that appears on customer statements")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def save(self, *args, **kwargs):
        # Encrypt sensitive values if not already encrypted
        if self.api_key and "gAAAAA" not in self.api_key:
            self.api_key = Crypto(self.api_key, 'encrypt').encrypt()
        if self.webhook_secret and "gAAAAA" not in self.webhook_secret:
            self.webhook_secret = Crypto(self.webhook_secret, 'encrypt').encrypt()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Card Payment Settings - {self.provider} ({'Test' if self.is_test_mode else 'Live'})"
    
    class Meta:
        verbose_name = "Card Payment Settings"
        verbose_name_plural = "Card Payment Settings"

class PayPalSettings(models.Model):
    """Settings for PayPal payment processing"""
    integration = models.ForeignKey(
        Integrations,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='paypal_settings',
        limit_choices_to={'integration_type': 'PAYMENT'}
    )
    # Sandbox vs Production
    is_test_mode = models.BooleanField(default=True, help_text="Use PayPal sandbox environment")
    
    # API credentials
    client_id = models.CharField(max_length=1500, default='your-paypal-client-id')
    client_secret = models.CharField(max_length=1500, default='your-paypal-client-secret')
    webhook_id = models.CharField(max_length=1500, blank=True, null=True)
    
    # Configuration
    base_url = models.URLField(
        default='https://api-m.sandbox.paypal.com', 
        help_text="API base URL. Use https://api-m.sandbox.paypal.com for sandbox, https://api-m.paypal.com for production"
    )
    webhook_url = models.URLField(default='https://yourdomain.com/api/payments/paypal/webhook', help_text="URL for PayPal webhooks")
    success_url = models.URLField(default='https://yourdomain.com/payment/success')
    cancel_url = models.URLField(default='https://yourdomain.com/payment/cancel')
    
    # Currency and business settings
    default_currency = models.CharField(max_length=3, default='KES')
    business_name = models.CharField(max_length=255, default='BengoERP')
    business_email = models.EmailField(max_length=255, default='payment@bengoerp.com')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def save(self, *args, **kwargs):
        # Update the base URL based on test mode
        if self.is_test_mode and 'sandbox' not in self.base_url:
            self.base_url = 'https://api-m.sandbox.paypal.com'
        elif not self.is_test_mode and 'sandbox' in self.base_url:
            self.base_url = 'https://api-m.paypal.com'
            
        # Encrypt sensitive values if not already encrypted
        if self.client_id and "gAAAAA" not in self.client_id:
            self.client_id = Crypto(self.client_id, 'encrypt').encrypt()
        if self.client_secret and "gAAAAA" not in self.client_secret:
            self.client_secret = Crypto(self.client_secret, 'encrypt').encrypt()
        if self.webhook_id and "gAAAAA" not in self.webhook_id:
            self.webhook_id = Crypto(self.webhook_id, 'encrypt').encrypt()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"PayPal Settings ({'Sandbox' if self.is_test_mode else 'Production'})"
    
    class Meta:
        verbose_name = "PayPal Settings"
        verbose_name_plural = "PayPal Settings"

# ---------------------------
# KRA / eTIMS Integration
# ---------------------------
class KRASettings(models.Model):
    """
    Kenya Revenue Authority (KRA) eTIMS system-to-system configuration.
    Stores encrypted credentials and endpoints required for authentication and invoice submission.
    """
    MODE_CHOICES = (
        ("sandbox", "Sandbox"),
        ("production", "Production"),
    )

    integration = models.OneToOneField(
        Integrations,
        on_delete=models.CASCADE,
        related_name='kra_settings',
        limit_choices_to={'integration_type': 'PAYMENT'},  # reuse Integrations registry
        null=True,
        blank=True,
    )

    # Environment
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='sandbox')
    base_url = models.URLField(
        default='https://api.sandbox.kra.go.ke',
        help_text="Base URL for KRA eTIMS APIs"
    )

    # Organization identifiers
    kra_pin = models.CharField(max_length=20, help_text="Business KRA PIN", blank=True, null=True)
    branch_code = models.CharField(max_length=10, help_text="Branch code if applicable", blank=True, null=True)

    # Credentials (encrypted on save)
    client_id = models.CharField(max_length=1500, blank=True, null=True)
    client_secret = models.CharField(max_length=1500, blank=True, null=True)
    username = models.CharField(max_length=255, blank=True, null=True)
    password = models.CharField(max_length=1500, blank=True, null=True)

    # Device identifiers for OSCU/VSCU
    device_serial = models.CharField(max_length=255, blank=True, null=True)
    pos_serial = models.CharField(max_length=255, blank=True, null=True)

    # Endpoint paths (allow override if KRA changes)
    token_path = models.CharField(max_length=255, default='/oauth/token')
    invoice_path = models.CharField(max_length=255, default='/etims/v1/invoices')
    invoice_status_path = models.CharField(max_length=255, default='/etims/v1/invoices/status')
    # Optional additional endpoints
    certificate_path = models.CharField(max_length=255, default='/etims/v1/certificates')
    compliance_path = models.CharField(max_length=255, default='/etims/v1/compliance')
    sync_path = models.CharField(max_length=255, default='/etims/v1/sync')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Encrypt sensitive fields if not already encrypted
        if self.client_id and "gAAAAA" not in self.client_id:
            self.client_id = Crypto(self.client_id, 'encrypt').encrypt()
        if self.client_secret and "gAAAAA" not in self.client_secret:
            self.client_secret = Crypto(self.client_secret, 'encrypt').encrypt()
        if self.password and "gAAAAA" not in self.password:
            self.password = Crypto(self.password, 'encrypt').encrypt()
        super().save(*args, **kwargs)

    def __str__(self):
        env = 'Sandbox' if self.mode == 'sandbox' else 'Production'
        return f"KRA Settings ({env})"

    class Meta:
        verbose_name = "KRA Settings"
        verbose_name_plural = "KRA Settings"

class KRACertificateRequest(models.Model):
    """
    Store KRA certificate request logs for audit and traceability.
    """
    CERT_TYPES = [
        ('tax_compliance', 'Tax Compliance'),
        ('vat', 'VAT'),
        ('paye', 'PAYE'),
    ]
    requested_by = models.ForeignKey('authmanagement.CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    cert_type = models.CharField(max_length=50, choices=CERT_TYPES)
    period = models.CharField(max_length=50)
    status = models.CharField(max_length=20, default='requested')
    response_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'KRA Certificate Request'
        verbose_name_plural = 'KRA Certificate Requests'
        indexes = [
            models.Index(fields=['cert_type']),
            models.Index(fields=['period']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

class KRAComplianceCheck(models.Model):
    """
    Store compliance check attempts and results.
    """
    kra_pin = models.CharField(max_length=20)
    is_compliant = models.BooleanField(default=False)
    response_payload = models.JSONField(null=True, blank=True)
    checked_by = models.ForeignKey('authmanagement.CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'KRA Compliance Check'
        verbose_name_plural = 'KRA Compliance Checks'
        indexes = [
            models.Index(fields=['kra_pin']),
            models.Index(fields=['is_compliant']),
            models.Index(fields=['created_at']),
        ]

# ---------------------------
# Webhook System
# ---------------------------
class WebhookEndpoint(models.Model):
    """Registered webhook endpoints for outbound events."""
    name = models.CharField(max_length=100)
    url = models.URLField()
    secret = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Webhook Endpoint'
        verbose_name_plural = 'Webhook Endpoints'
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['is_active']),
        ]

class WebhookEvent(models.Model):
    """Outbound webhook event queue and delivery status."""
    EVENT_STATUSES = [
        ('pending', 'Pending'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('retrying', 'Retrying'),
    ]
    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    status = models.CharField(max_length=20, choices=EVENT_STATUSES, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.event_type} -> {self.endpoint.name}"

    class Meta:
        verbose_name = 'Webhook Event'
        verbose_name_plural = 'Webhook Events'
        indexes = [
            models.Index(fields=['event_type']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]