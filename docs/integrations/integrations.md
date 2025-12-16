# ERP Service - Integration Guide

## Overview

This document provides detailed integration information for all external services and systems integrated with the ERP service, including internal BengoBox microservices and external third-party services.

---

## Table of Contents

1. [Internal BengoBox Service Integrations](#internal-bengobox-service-integrations)
2. [External Third-Party Integrations](#external-third-party-integrations)
3. [Integration Patterns](#integration-patterns)
4. [Two-Tier Configuration Management](#two-tier-configuration-management)
5. [Event-Driven Architecture](#event-driven-architecture)
6. [Integration Security](#integration-security)
7. [Error Handling & Resilience](#error-handling--resilience)

---

## Internal BengoBox Service Integrations

### Auth Service

**Integration Type**: OAuth2/OIDC + Events + REST

**Use Cases**:
- User authentication and authorization
- JWT token validation
- User identity synchronization
- Tenant/outlet discovery

**Architecture**:
- JWT validation middleware for all protected routes
- User sync endpoint for SSO compatibility

**Events Consumed**:
- `auth.tenant.created` - Initialize tenant in ERP system
- `auth.tenant.updated` - Update tenant metadata
- `auth.user.created` - Create user in ERP (if needed)
- `auth.user.updated` - Update user identity fields

### Notifications Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- Invoice/bill notifications
- Payment reminders
- Payroll notifications
- Leave approval notifications
- Order confirmations
- Campaign emails
- Task notifications

**REST API Usage**:
- `POST /api/v1/notifications/messages` - Send notification

**Events Published**:
- `erp.invoice.created` - Invoice created
- `erp.invoice.sent` - Invoice sent to customer
- `erp.payment.received` - Payment received
- `erp.payroll.processed` - Payroll processed
- `erp.order.created` - Order created
- `erp.leave.requested` - Leave request submitted

### Treasury Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- Payment processing
- Bank account synchronization
- Financial transaction reconciliation
- Tax calculation and reporting

**REST API Usage**:
- `POST /api/v1/treasury/payments` - Process payment
- `GET /api/v1/treasury/accounts` - Get bank accounts
- `POST /api/v1/treasury/reconciliations` - Create reconciliation

**Events Published**:
- `erp.invoice.created` - For payment processing
- `erp.bill.created` - For bill payment
- `erp.payroll.processed` - For payroll payments

**Events Consumed**:
- `treasury.payment.processed` - Payment processed
- `treasury.account.synced` - Bank account synced
- `treasury.reconciliation.completed` - Reconciliation completed

### Inventory Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- Stock level synchronization
- Inventory movements
- Stock adjustments
- Inventory reporting

**REST API Usage**:
- `GET /api/v1/inventory/items/{id}/stock` - Get stock levels
- `POST /api/v1/inventory/movements` - Record stock movement

**Events Published**:
- `erp.order.created` - For inventory reservation
- `erp.purchase_order.received` - For stock receipt
- `erp.work_order.completed` - For finished goods

**Events Consumed**:
- `inventory.stock.updated` - Stock level updated
- `inventory.movement.recorded` - Stock movement recorded

### Logistics Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- Order fulfillment
- Shipping and delivery tracking
- Delivery notifications

**REST API Usage**:
- `POST /api/v1/logistics/shipments` - Create shipment
- `GET /api/v1/logistics/shipments/{id}/tracking` - Get tracking info

**Events Published**:
- `erp.order.fulfilled` - Order ready for shipping

**Events Consumed**:
- `logistics.shipment.created` - Shipment created
- `logistics.shipment.delivered` - Shipment delivered

### POS Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- POS order synchronization
- Product catalog sync
- Sales reporting

**REST API Usage**:
- `GET /api/v1/pos/products` - Get product catalog
- `POST /api/v1/pos/orders` - Create POS order

**Events Published**:
- `erp.product.updated` - Product catalog updated

**Events Consumed**:
- `pos.order.created` - POS order created

### IoT Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- Asset monitoring via IoT devices
- Production line monitoring
- Environmental monitoring for inventory

**REST API Usage**:
- `GET /api/v1/iot/devices/{id}/telemetry` - Get device telemetry

**Events Consumed**:
- `iot.telemetry.received` - Device telemetry received
- `iot.alert.triggered` - Device alert triggered

### Projects Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- Project expense tracking
- Project budget management
- Resource allocation

**REST API Usage**:
- `POST /api/v1/projects/{id}/expenses` - Record project expense
- `GET /api/v1/projects/{id}/budget` - Get project budget

**Events Published**:
- `erp.expense.created` - Expense created (for project tracking)

**Events Consumed**:
- `projects.budget.updated` - Project budget updated

---

## External Third-Party Integrations

### Payment Gateways (via Treasury Service)

**Purpose**: Payment processing for invoices, bills, and orders

**Configuration** (Tier 1):
- Gateway credentials: Stored encrypted
- API keys: Stored encrypted
- Webhook endpoints: Configured

**Use Cases**:
- Invoice payment processing
- Bill payment processing
- Order payment processing

**Integration**: Handled via treasury-app, ERP publishes events

### KRA iTax (via Treasury Service)

**Purpose**: Tax compliance and reporting

**Configuration** (Tier 1):
- KRA API credentials: Stored encrypted
- Tax registration numbers: Stored encrypted

**Use Cases**:
- Tax calculation
- Tax return filing
- Tax compliance reporting

**Integration**: Handled via treasury-app, ERP publishes tax events

### Email Providers (via Notifications Service)

**Purpose**: Email notifications and campaigns

**Configuration** (Tier 1):
- SMTP credentials: Stored encrypted
- API keys: Stored encrypted

**Use Cases**:
- Invoice/bill emails
- Campaign emails
- Notification emails

**Integration**: Handled via notifications-service, ERP publishes events

### SMS Providers (via Notifications Service)

**Purpose**: SMS notifications

**Configuration** (Tier 1):
- SMS provider credentials: Stored encrypted
- API keys: Stored encrypted

**Use Cases**:
- Payment reminders
- Order confirmations
- Leave approvals

**Integration**: Handled via notifications-service, ERP publishes events

### Cloud Storage (Future)

**Purpose**: Document storage (invoices, bills, reports)

**Configuration** (Tier 1):
- Storage credentials: Stored encrypted
- Bucket configuration: Stored encrypted

**Use Cases**:
- Invoice PDF storage
- Report storage
- Document archiving

---

## Integration Patterns

### 1. REST API Pattern (Synchronous)

**Use Case**: Data retrieval, immediate operations

**Implementation**:
- Django REST Framework HTTP client
- Retry logic with exponential backoff
- Circuit breaker pattern
- Request timeout (10 seconds default)
- Idempotency keys for mutations

### 2. Event-Driven Pattern (Asynchronous)

**Use Case**: Cross-service communication, notifications

**Transport**: Celery with RabbitMQ/NATS

**Flow**:
1. Service publishes event to message broker
2. Subscriber services consume event
3. Process event and update local state
4. Publish response events if needed

**Reliability**:
- At-least-once delivery
- Event deduplication via event_id
- Retry on failure
- Dead letter queue for failed events

### 3. Webhook Pattern (Callbacks)

**Use Case**: External provider callbacks, ERP events

**Implementation**:
- Webhook endpoints in ERP service
- Signature verification (HMAC-SHA256)
- Retry logic for failed deliveries
- Idempotency handling

### 4. Database Polling (Avoided)

**Note**: Polling is explicitly avoided. Use event-driven or webhook patterns instead.

---

## Two-Tier Configuration Management

### Tier 1: Developer/Superuser Configuration

**Visibility**: Only developers and superusers

**Configuration Items**:
- Database credentials
- External API credentials
- Encryption keys
- Service-to-service API keys

**Storage**:
- Encrypted at rest in database (AES-256-GCM)
- K8s secrets for runtime
- Vault for production secrets

### Tier 2: Business User Configuration

**Visibility**: Normal system users (tenant admins)

**Configuration Items**:
- Business settings
- Tax rates
- Payment terms
- Notification preferences
- Report templates

**Storage**:
- Plain text in database (non-sensitive)
- Tenant-specific configuration tables

---

## Event-Driven Architecture

### Event Catalog

#### Outbound Events (Published by ERP Service)

**erp.invoice.created**
```json
{
  "event_id": "uuid",
  "event_type": "erp.invoice.created",
  "tenant_id": "tenant-uuid",
  "timestamp": "2024-12-05T10:30:00Z",
  "data": {
    "invoice_id": "invoice-uuid",
    "invoice_number": "INV-001",
    "customer_id": "customer-uuid",
    "amount": 1000.00,
    "currency": "KES"
  }
}
```

**erp.payment.received**
```json
{
  "event_id": "uuid",
  "event_type": "erp.payment.received",
  "tenant_id": "tenant-uuid",
  "timestamp": "2024-12-05T10:30:00Z",
  "data": {
    "payment_id": "payment-uuid",
    "invoice_id": "invoice-uuid",
    "amount": 1000.00,
    "payment_method": "mpesa"
  }
}
```

**erp.payroll.processed**
```json
{
  "event_id": "uuid",
  "event_type": "erp.payroll.processed",
  "tenant_id": "tenant-uuid",
  "timestamp": "2024-12-05T10:30:00Z",
  "data": {
    "payroll_id": "payroll-uuid",
    "period": "2024-12",
    "total_amount": 50000.00,
    "employee_count": 10
  }
}
```

#### Inbound Events (Consumed by ERP Service)

**treasury.payment.processed**
```json
{
  "event_id": "uuid",
  "event_type": "treasury.payment.processed",
  "tenant_id": "tenant-uuid",
  "timestamp": "2024-12-05T10:30:00Z",
  "data": {
    "payment_id": "payment-uuid",
    "invoice_id": "invoice-uuid",
    "status": "completed",
    "amount": 1000.00
  }
}
```

**inventory.stock.updated**
```json
{
  "event_id": "uuid",
  "event_type": "inventory.stock.updated",
  "tenant_id": "tenant-uuid",
  "timestamp": "2024-12-05T10:30:00Z",
  "data": {
    "item_id": "item-uuid",
    "stock_level": 100,
    "warehouse_id": "warehouse-uuid"
  }
}
```

---

## Integration Security

### Authentication

**JWT Tokens**:
- Validated via auth-service
- Token claims include tenant_id for scoping

**API Keys** (Service-to-Service):
- Stored in K8s secrets
- Rotated quarterly

### Authorization

**Tenant Isolation**:
- All requests scoped by tenant_id
- Data access isolated per tenant
- Data isolation enforced at database level

### Secrets Management

**Encryption**:
- Secrets encrypted at rest (AES-256-GCM)
- Decrypted only when used
- Key rotation every 90 days

---

## Error Handling & Resilience

### Retry Policies

**Exponential Backoff**:
- Initial delay: 1 second
- Max delay: 30 seconds
- Max retries: 3

### Circuit Breaker

**Implementation**:
- Opens after 5 consecutive failures
- Half-open after 60 seconds
- Closes on successful request

### Monitoring

**Metrics**:
- API call latency (p50, p95, p99)
- API call success/failure rates
- Event publishing success rates
- Integration health status

**Alerts**:
- High failure rate (>5%)
- Service unavailability
- Event delivery failures
- Integration timeout

---

## References

- [Auth Service Integration](../auth-service/auth-service/docs/integrations.md)
- [Treasury Service Integration](../finance-service/treasury-app/docs/integrations.md)
- [Inventory Service Integration](../inventory-service/inventory-api/docs/integrations.md)
- [Logistics Service Integration](../logistics-service/logistics-api/docs/integrations.md)
- [Notifications Service Integration](../notifications-service/notifications-api/docs/integrations.md)

