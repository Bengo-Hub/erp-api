# ERP Service - Integration Guide

## Overview

This document provides detailed integration information for all external services and systems integrated with the ERP service. **ERP focuses on CRM, HRM, Procurement, Manufacturing, and E-commerce modules**, and integrates with specialized microservices for finance, inventory, authentication, and notifications.

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
- **ERP does NOT manage users** - all user management is handled by auth-service

**Events Consumed**:
- `auth.tenant.created` - Initialize tenant in ERP system
- `auth.tenant.updated` - Update tenant metadata
- `auth.user.created` - Sync user reference (if needed)
- `auth.user.updated` - Update user identity fields

### Notifications Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- Payroll notifications
- Leave approval notifications
- Order confirmations
- Campaign emails
- Lead notifications
- PO notifications
- Work order notifications

**REST API Usage**:
- `POST /api/v1/notifications/messages` - Send notification

**Events Published**:
- `erp.payroll.processed` - Payroll processed
- `erp.leave.requested` - Leave request submitted
- `erp.order.created` - Order created
- `erp.campaign.sent` - Campaign email sent
- `erp.lead.qualified` - Lead qualified
- `erp.purchase_order.created` - PO created
- `erp.work_order.completed` - Work order completed

**Note**: ERP does NOT send notifications directly - all notifications are handled by notifications-service.

### Treasury Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- Invoice generation (from CRM opportunities)
- Bill creation (from purchase orders)
- Payment processing (for orders, payroll)
- Expense recording (from HRM expenses)
- Tax calculation and reporting
- Financial reconciliation

**REST API Usage**:
- `POST /api/v1/treasury/invoices` - Create invoice
- `POST /api/v1/treasury/bills` - Create bill
- `POST /api/v1/treasury/payments` - Process payment
- `POST /api/v1/treasury/expenses` - Record expense
- `GET /api/v1/treasury/accounts` - Get bank accounts
- `GET /api/v1/treasury/tax-codes` - Get tax codes

**Events Published**:
- `erp.opportunity.won` - Opportunity won (create invoice)
- `erp.purchase_order.received` - PO received (create bill)
- `erp.payroll.processed` - Payroll processed (create payments)
- `erp.expense.approved` - Expense approved (record expense)

**Events Consumed**:
- `treasury.invoice.created` - Invoice created
- `treasury.payment.processed` - Payment processed
- `treasury.bill.created` - Bill created

**Note**: ERP does NOT manage financial transactions, invoices, bills, payments, or accounting - all financial operations are handled by treasury-app.

### Inventory Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- Stock level queries (for e-commerce products)
- Stock movements (for purchase orders, work orders)
- Stock adjustments (for manufacturing)
- Inventory reporting

**REST API Usage**:
- `GET /api/v1/inventory/items/{id}/stock` - Get stock levels
- `POST /api/v1/inventory/movements` - Record stock movement
- `POST /api/v1/inventory/adjustments` - Record stock adjustment
- `GET /api/v1/inventory/warehouses` - Get warehouses

**Events Published**:
- `erp.order.created` - For inventory reservation
- `erp.purchase_order.received` - For stock receipt
- `erp.work_order.completed` - For finished goods
- `erp.work_order.started` - For material consumption

**Events Consumed**:
- `inventory.stock.updated` - Stock level updated
- `inventory.movement.recorded` - Stock movement recorded
- `inventory.reservation.created` - Reservation created

**Note**: ERP does NOT manage inventory balances or stock levels - all inventory management is handled by inventory-service.

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
- Product catalog sync
- Sales reporting
- POS order synchronization

**REST API Usage**:
- `GET /api/v1/pos/products` - Get product catalog
- `POST /api/v1/pos/orders` - Create POS order

**Events Published**:
- `erp.product.updated` - Product catalog updated

**Events Consumed**:
- `pos.order.created` - POS order created

**Note**: ERP's e-commerce module manages product catalog, but POS operations are handled by pos-service.

### IoT Service

**Integration Type**: Events (Celery/RabbitMQ) + REST API

**Use Cases**:
- Production line monitoring (for manufacturing)
- Environmental monitoring (for quality control)

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

**Integration**: Handled via treasury-app, ERP publishes events

**Configuration** (Tier 1 - in treasury-app):
- Gateway credentials: Stored encrypted
- API keys: Stored encrypted
- Webhook endpoints: Configured

### KRA iTax (via Treasury Service)

**Purpose**: Tax compliance and reporting

**Integration**: Handled via treasury-app, ERP publishes tax events

**Configuration** (Tier 1 - in treasury-app):
- KRA API credentials: Stored encrypted
- Tax registration numbers: Stored encrypted

### Email Providers (via Notifications Service)

**Purpose**: Email notifications and campaigns

**Integration**: Handled via notifications-service, ERP publishes events

**Configuration** (Tier 1 - in notifications-service):
- SMTP credentials: Stored encrypted
- API keys: Stored encrypted

### SMS Providers (via Notifications Service)

**Purpose**: SMS notifications

**Integration**: Handled via notifications-service, ERP publishes events

**Configuration** (Tier 1 - in notifications-service):
- SMS provider credentials: Stored encrypted
- API keys: Stored encrypted

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
- External API credentials (for integrations)
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
- Tax rates (references from treasury-app)
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

**erp.opportunity.won**
```json
{
  "event_id": "uuid",
  "event_type": "erp.opportunity.won",
  "tenant_id": "tenant-uuid",
  "timestamp": "2024-12-05T10:30:00Z",
  "data": {
    "opportunity_id": "opportunity-uuid",
    "customer_id": "customer-uuid",
    "amount": 10000.00,
    "currency": "KES"
  }
}
```

**erp.purchase_order.received**
```json
{
  "event_id": "uuid",
  "event_type": "erp.purchase_order.received",
  "tenant_id": "tenant-uuid",
  "timestamp": "2024-12-05T10:30:00Z",
  "data": {
    "purchase_order_id": "po-uuid",
    "vendor_id": "vendor-uuid",
    "total_amount": 5000.00,
    "currency": "KES"
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

**treasury.invoice.created**
```json
{
  "event_id": "uuid",
  "event_type": "treasury.invoice.created",
  "tenant_id": "tenant-uuid",
  "timestamp": "2024-12-05T10:30:00Z",
  "data": {
    "invoice_id": "invoice-uuid",
    "opportunity_id": "opportunity-uuid",
    "status": "sent"
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

