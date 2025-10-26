# Integration Architecture

## Overview

The BengoERP Integration module provides a centralized, secure, and flexible framework for managing all external service integrations including payment providers, government services, and notification channels.

## Key Features

- **Centralized Configuration**: All integration settings stored in database with admin interface
- **Encrypted Secrets**: Automatic encryption at rest for API keys, tokens, and credentials
- **Default Values**: System provides defaults when DB settings not configured
- **Health Checks**: Built-in connectivity testing for all integrations
- **Multi-Environment**: Sandbox/test and production environment support
- **Caching**: Configuration caching for performance
- **Audit Trail**: Track integration usage and changes

## Architecture

### Core Components

```
integrations/
├── models.py                    # Integration settings models
├── services/
│   ├── config_service.py       # Centralized config with defaults & decryption
│   └── notification_service.py # Notification analytics
├── payments/
│   ├── mpesa_payment.py        # M-Pesa service
│   ├── card_payment.py         # Card payment service
│   └── paypal_payment.py       # PayPal service
├── services.py                  # KRA & Webhook services
├── utils.py                     # Crypto utilities
├── health_views.py             # Health check endpoints
├── views.py                     # Integration CRUD
└── urls.py                      # API routes
```

## Supported Integrations

### Payment Integrations

#### 1. M-Pesa (Safaricom)
- **Provider**: Safaricom M-Pesa
- **Features**: STK Push, payment status query, callbacks
- **Model**: `MpesaSettings`
- **Service**: `MpesaPaymentService`
- **Encrypted Fields**: consumer_key, consumer_secret, passkey, security_credential

**Configuration Fields**:
- `consumer_key`: M-Pesa API consumer key
- `consumer_secret`: M-Pesa API consumer secret
- `passkey`: Lipa Na M-Pesa passkey
- `short_code`: Paybill/Till number
- `base_url`: API endpoint (sandbox/production)
- `callback_base_url`: Your callback URL
- `initiator_name`: Initiator username
- `security_credential`: Encrypted initiator password

#### 2. Card Payments (Stripe/Others)
- **Provider**: Stripe (default), configurable
- **Features**: Card authorization, capture, refund
- **Model**: `CardPaymentSettings`
- **Service**: `CardPaymentService`
- **Encrypted Fields**: api_key, webhook_secret

**Configuration Fields**:
- `provider`: Payment processor (STRIPE, etc.)
- `is_test_mode`: Use sandbox environment
- `api_key`: Secret API key
- `public_key`: Publishable key
- `webhook_secret`: Webhook signature secret
- `base_url`: API base URL
- `default_currency`: Default currency (KES)

#### 3. PayPal
- **Provider**: PayPal
- **Features**: Order creation, capture, refund
- **Model**: `PayPalSettings`
- **Service**: `PayPalPaymentService`
- **Encrypted Fields**: client_id, client_secret, webhook_id

**Configuration Fields**:
- `is_test_mode`: Use sandbox
- `client_id`: PayPal client ID
- `client_secret`: PayPal client secret
- `base_url`: Auto-switched based on mode
- `default_currency`: Default currency (KES)

### Government Services

#### 4. KRA eTIMS
- **Provider**: Kenya Revenue Authority
- **Features**: Invoice submission, compliance checks, certificates
- **Model**: `KRASettings`
- **Service**: `KRAService`
- **Encrypted Fields**: client_id, client_secret, password

**Configuration Fields**:
- `mode`: sandbox/production
- `base_url`: KRA API endpoint
- `kra_pin`: Business KRA PIN
- `client_id`: OAuth client ID
- `client_secret`: OAuth client secret
- `username`: API username
- `password`: API password
- `device_serial`: OSCU/VSCU serial
- Configurable endpoint paths

**Methods**:
- `get_access_token()`: OAuth2 authentication
- `submit_invoice()`: Submit invoice to eTIMS
- `get_invoice_status()`: Query invoice status
- `get_tax_certificate()`: Request tax compliance certificate
- `check_compliance()`: Check PIN compliance
- `sync_tax_data()`: Sync tax data for period

### Bank API Integration

#### 5. Bank APIs
- **Providers**: Equity, KCB, Co-op, NCBA, Absa, Standard Chartered, DTB, Barclays, Others
- **Features**: Account balance, statements, transfers, bulk payments
- **Model**: `BankAPISettings`
- **Encrypted Fields**: client_id, client_secret, api_key, api_secret

**Configuration Fields**:
- `bank_provider`: Bank identifier
- `bank_name`: Full bank name
- `bank_code`: SWIFT/bank code
- `is_test_mode`: Sandbox/production
- `base_url`/`sandbox_url`: API URLs
- `client_id`, `client_secret`: OAuth credentials
- `api_key`, `api_secret`: API credentials
- `organization_id`: Org identifier
- `account_number`: Primary account
- Configurable endpoint paths for balance, statements, transfers, etc.

### Government Services (Extended)

#### 6. Government Service Integration
- **Providers**: eCitizen, Huduma Kenya, NTSA, NITA, NSSF, NHIF, HELB, IPRS
- **Features**: Query services, submit applications, check status
- **Model**: `GovernmentServiceSettings`
- **Encrypted Fields**: client_id, client_secret, api_key, api_token, password

**Configuration Fields**:
- `service_provider`: Service identifier
- `service_name`: Full service name
- `is_test_mode`: Sandbox/production
- `client_id`, `client_secret`: OAuth credentials
- `api_key`, `api_token`: API credentials
- `username`, `password`: Basic auth
- `organization_id`, `organization_code`: Org identifiers
- Configurable endpoint paths

### Notification Integrations

#### 7. SMS Providers
- **Providers**: AfricasTalking, Twilio, Nexmo/Vonage, AWS SNS
- **Model**: `SMSConfiguration` (in notifications app)
- **Service**: `SMSService`
- **Encrypted Fields**: api_key, auth_token, account_sid, aws_access_key, aws_secret_key

#### 8. Email Providers
- **Providers**: SMTP, SendGrid, Mailgun, Amazon SES, Mandrill
- **Model**: `EmailConfiguration` (in notifications app)
- **Service**: `EmailService`
- **Encrypted Fields**: smtp_password, api_key, api_secret

## Configuration Service

### `IntegrationConfigService`

Centralized service providing:
- Unified config access for all integrations
- Automatic decryption of secrets
- Default values when DB not configured
- Configuration caching
- Health check methods

#### Key Methods

```python
# Get M-Pesa config with decrypted secrets
config = IntegrationConfigService.get_mpesa_config(decrypt_secrets=True)

# Get KRA config
config = IntegrationConfigService.get_kra_config(decrypt_secrets=True)

# Test connectivity
success, message = IntegrationConfigService.test_mpesa_connection()
success, message = IntegrationConfigService.test_kra_connection()

# Get all integration status
status = IntegrationConfigService.get_all_integration_status()

# Clear cache after config changes
IntegrationConfigService.clear_config_cache()
```

#### Default Configurations

The service provides sensible defaults for all integrations when DB settings don't exist:

- **M-Pesa**: Sandbox URLs, test shortcode (174379)
- **KRA**: Sandbox mode, sandbox URLs
- **SMS**: AfricasTalking sandbox
- **Email**: Gmail SMTP defaults
- **Card**: Stripe sandbox mode

## Security

### Encryption at Rest

All sensitive fields auto-encrypt on save using Fernet (symmetric encryption):

```python
def save(self, *args, **kwargs):
    # Check if already encrypted (marker: gAAAAA)
    if self.api_key and "gAAAAA" not in self.api_key:
        self.api_key = Crypto(self.api_key, 'encrypt').encrypt()
    super().save(*args, **kwargs)
```

### Decryption

Decryption happens at runtime when needed:

```python
api_key = Crypto(encrypted_api_key, 'decrypt').decrypt()
```

### Encryption Key Management

- Encryption key stored in `AppSettings.cypher_key`
- Falls back to environment variable `CYPHER_KEY`
- Default key provided for dev (should be changed in production)
- Super admin can update encryption key via admin panel

## Health Check Endpoints

### Available Endpoints

```
GET /api/v1/integrations/health/
    - All integrations health status
    
GET /api/v1/integrations/health/mpesa/
    - M-Pesa connectivity test
    
GET /api/v1/integrations/health/kra/
    - KRA API connectivity test
    
GET /api/v1/integrations/health/sms/
    - SMS provider connectivity test
    
GET /api/v1/integrations/health/email/
    - Email provider connectivity test
    
POST /api/v1/integrations/cache/clear/
    - Clear config cache (admin only)
    
GET /api/v1/integrations/summary/
    - Integration configuration summary
```

### Health Check Response Format

```json
{
  "success": true,
  "integrations": {
    "mpesa": {
      "configured": true,
      "active": true,
      "connection": [true, "M-Pesa connection successful"]
    },
    "kra": {
      "configured": true,
      "connection": [true, "KRA connection successful"]
    },
    "sms": {
      "configured": true,
      "connection": [false, "AfricasTalking API key not set"]
    },
    "email": {
      "configured": true,
      "connection": [true, "SMTP connection successful"]
    }
  },
  "generated_at": "2025-10-22T10:30:00Z"
}
```

## Webhook System

### Webhook Endpoints
- Register webhook endpoints for outbound events
- HMAC signature verification
- Automatic retry with exponential backoff
- Event delivery tracking

### Models
- `WebhookEndpoint`: Registered webhook URLs
- `WebhookEvent`: Event queue and delivery status

### Service
- `WebhookDeliveryService`: Handles delivery with retries

## Usage Examples

### 1. Configure M-Pesa (Admin Panel)

1. Go to Django Admin → Integrations → M-Pesa Settings
2. Add new M-Pesa Settings
3. Enter credentials (auto-encrypted on save):
   - Consumer Key
   - Consumer Secret
   - Passkey
   - Short Code
   - Base URL (use sandbox URL for testing)
   - Callback URL
4. Save

### 2. Use M-Pesa in Code

```python
from integrations.payments.mpesa_payment import MpesaPaymentService

# Initiate STK Push
success, message, data = MpesaPaymentService.initiate_stk_push(
    phone='254712345678',
    amount=1000,
    account_reference='INV001',
    description='Order payment'
)

if success:
    checkout_id = data['checkout_id']
    # Store checkout_id for later status query
```

### 3. Use KRA Service

```python
from integrations.services import KRAService

kra_service = KRAService()

# Get access token
success, token = kra_service.get_access_token()

# Submit invoice
success, response = kra_service.submit_invoice({
    'invoice_number': 'INV001',
    # ... invoice data
})

# Check compliance
success, result = kra_service.check_compliance('P051234567X')
```

### 4. Test Integration Health

```python
from integrations.services import IntegrationConfigService

# Test M-Pesa
success, message = IntegrationConfigService.test_mpesa_connection()
print(f"M-Pesa: {message}")

# Get all status
status = IntegrationConfigService.get_all_integration_status()
```

## Admin Panel Configuration

Super admins can configure all integrations through Django Admin:

1. **Integrations**: Manage integration registry
2. **M-Pesa Settings**: Configure M-Pesa
3. **Card Payment Settings**: Configure Stripe/card processor
4. **PayPal Settings**: Configure PayPal
5. **KRA Settings**: Configure KRA eTIMS
6. **Bank API Settings**: Configure bank integrations
7. **Government Service Settings**: Configure govt services
8. **Notification Integrations**: SMS, Email, Push (in notifications app)

All sensitive fields show as password inputs and are encrypted on save.

## Best Practices

1. **Always use sandbox/test mode** for development
2. **Test connectivity** using health check endpoints after configuration
3. **Clear config cache** after updating settings
4. **Monitor webhook events** for failed deliveries
5. **Use IntegrationConfigService** for centralized config access
6. **Rotate encryption keys** periodically in production
7. **Never log decrypted secrets**
8. **Set proper callback URLs** for production
9. **Validate credentials** using health checks before going live
10. **Keep API documentation handy** for each provider

## Migration to Production

Before going live:

1. Configure production credentials in admin
2. Switch `is_test_mode` to `False`
3. Update `base_url` to production endpoints
4. Set production callback URLs
5. Test connectivity using health endpoints
6. Clear config cache
7. Monitor initial transactions closely
8. Set up webhook monitoring

## Troubleshooting

### Common Issues

1. **"Settings not configured"**
   - Add settings in Django Admin for the integration

2. **"Connection failed"**
   - Check credentials are correct
   - Verify base URL is correct for environment
   - Test using health check endpoint
   - Check network/firewall rules

3. **"Decryption error"**
   - Verify encryption key is set correctly
   - Check `AppSettings.cypher_key` matches key used to encrypt

4. **"Cached config outdated"**
   - Call `/api/v1/integrations/cache/clear/` (admin only)

5. **"Webhook delivery failed"**
   - Check webhook URL is accessible
   - Verify HMAC signature verification
   - Review `WebhookEvent` model for error details

## Future Enhancements

- OAuth2 token caching and refresh
- Integration usage analytics dashboard
- Rate limiting per integration
- Multi-tenancy support (per-business configs)
- Integration marketplace
- Automated credential rotation
- Real-time integration status monitoring
- Cost tracking per integration

## Related Documentation

- [Project Architecture](architecture-overview.md)
- [Plan](plan.md)
- [Task Breakdown](task-breakdown.md)
- [Payroll Tax Updates](payroll-tax-updates-2025.md)

