# API Endpoints Documentation

**Document Date**: March 1, 2026  
**Version**: 1.0  
**Base URL**: `https://api.erp.example.com/api/`

---

## Table of Contents

1. [Authentication](#authentication)
2. [Invoice Endpoints](#invoice-endpoints)
3. [Delivery Note Endpoints](#delivery-note-endpoints)
4. [Payment Endpoints](#payment-endpoints)
5. [Purchase Order Endpoints](#purchase-order-endpoints)
6. [Common Patterns](#common-patterns)
7. [Error Handling](#error-handling)

---

## Authentication

### JWT Token Authentication

All endpoints require authentication via JWT Bearer token.

**Headers**:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Content-Type: application/json
```

**Obtain Token**:
```http
POST /auth/token/
Content-Type: application/json

{
    "email": "user@example.com",
    "password": "secure_password"
}

Response:
{
    "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expires_in": 3600
}
```

**Refresh Token**:
```http
POST /auth/token/refresh/
Content-Type: application/json

{
    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

---

## Invoice Endpoints

### List Invoices

```http
GET /invoices/
```

**Query Parameters**:
| Parameter | Type | Description | Examples |
|-----------|------|-------------|----------|
| status | string | Filter by status | draft, sent, paid, overdue |
| customer_id | integer | Filter by customer | 123 |
| created_after | date | Filter by date | 2026-01-01 |
| search | string | Search number/customer | INV0001 |
| ordering | string | Sort field | -invoice_date, total |
| page | integer | Page number | 1, 2, 3 |
| page_size | integer | Items per page | 10, 20, 50 |

**Example Request**:
```bash
curl -H "Authorization: Bearer TOKEN" \
  "https://api.erp.example.com/api/invoices/?status=draft&page=1"
```

**Response (200 OK)**:
```json
{
    "count": 150,
    "next": "https://api.erp.example.com/api/invoices/?page=2",
    "previous": null,
    "results": [
        {
            "id": 1,
            "invoice_number": "INV0001-260301",
            "customer": {
                "id": 1,
                "name": "Acme Corp",
                "email": "contact@acme.com"
            },
            "invoice_date": "2026-03-01",
            "due_date": "2026-03-31",
            "status": "draft",
            "total": "5000.00",
            "balance_due": "5000.00",
            "items_count": 3
        }
    ]
}
```

### Create Invoice

```http
POST /invoices/
Content-Type: application/json
```

**Request Body**:
```json
{
    "customer": 1,
    "branch": 2,
    "invoice_date": "2026-03-01",
    "due_date": "2026-03-31",
    "payment_terms": "net_30",
    "items": [
        {
            "product_id": 100,
            "name": "Product A",
            "quantity": 5,
            "unit_price": "100.00",
            "tax_rate": "16"
        }
    ],
    "customer_notes": "Thank you for your business",
    "terms_and_conditions": "30 days net"
}
```

**Response (201 Created)**:
```json
{
    "id": 1,
    "invoice_number": "INV0001-260301",
    "status": "draft",
    "total": "5800.00",
    "balance_due": "5800.00",
    "pdf_base64": "JVBERi0xLjQK... (base64 encoded PDF)"
}
```

### Retrieve Invoice

```http
GET /invoices/{id}/
```

**Response (200 OK)**:
```json
{
    "id": 1,
    "invoice_number": "INV0001-260301",
    "customer": {...},
    "items": [
        {
            "id": 1,
            "name": "Product A",
            "quantity": 5,
            "unit_price": "100.00",
            "total_price": "500.00"
        }
    ],
    "subtotal": "500.00",
    "tax_amount": "80.00",
    "total": "580.00",
    "balance_due": "580.00",
    "status": "draft"
}
```

### Send Invoice

```http
POST /invoices/{id}/send/
Content-Type: application/json
```

**Request Body**:
```json
{
    "recipient_email": "customer@example.com",
    "message": "Please find attached your invoice",
    "schedule_send": false
}
```

**Response (200 OK)**:
```json
{
    "status": "sent",
    "sent_at": "2026-03-01T10:30:00Z",
    "recipient_email": "customer@example.com",
    "message": "Invoice sent successfully"
}
```

### Record Payment

```http
POST /invoices/{id}/record-payment/
Content-Type: application/json
```

**Request Body**:
```json
{
    "amount": "500.00",
    "payment_date": "2026-03-01",
    "payment_method": "bank_transfer",
    "payment_account": 1,
    "reference": "CHQ-12345",
    "notes": "Check deposited"
}
```

**Response (200 OK)**:
```json
{
    "id": 1,
    "amount_paid": "500.00",
    "balance_due": "80.00",
    "status": "partially_paid",
    "payment_invoice": {
        "id": 1,
        "amount": "500.00",
        "payment_date": "2026-03-01",
        "created_at": "2026-03-01T10:30:00Z"
    }
}
```

### Mark Invoice as Paid

```http
POST /invoices/{id}/mark-paid/
Content-Type: application/json
```

**Request Body**:
```json
{
    "amount": "5800.00",
    "payment_date": "2026-03-01",
    "notes": "Full payment received"
}
```

### Void Invoice

```http
POST /invoices/{id}/void/
Content-Type: application/json
```

**Request Body**:
```json
{
    "reason": "Duplicate invoice issued"
}
```

### Download Invoice PDF

```http
GET /invoices/{id}/pdf/
```

**Response**: PDF file (Content-Type: application/pdf)

---

## Delivery Note Endpoints

### List Delivery Notes

```http
GET /delivery-notes/
```

**Query Parameters**:
| Parameter | Type |
|-----------|------|
| status | draft, confirmed, in_transit, delivered |
| source_invoice | Invoice ID |
| delivery_date_from | Date |
| delivery_date_to | Date |
| search | Search by delivery number |

### Create Delivery Note

```http
POST /delivery-notes/
Content-Type: application/json
```

**Request Body**:
```json
{
    "source_invoice": 1,
    "delivery_date": "2026-03-05",
    "delivery_address": "123 Main St, City, ZIP",
    "driver_name": "John Doe",
    "driver_phone": "+254123456789",
    "vehicle_number": "ABC-123",
    "special_instructions": "Handle with care"
}
```

**Response (201 Created)**:
```json
{
    "id": 1,
    "delivery_note_number": "POD0001-260305",
    "source_invoice": 1,
    "status": "draft",
    "delivery_date": "2026-03-05"
}
```

### Create from Invoice

```http
POST /delivery-notes/from-invoice/
Content-Type: application/json
```

**Request Body**:
```json
{
    "invoice": 1,
    "delivery_address": "123 Main St",
    "driver_name": "John Doe"
}
```

### Mark Delivered

```http
POST /delivery-notes/{id}/mark-delivered/
Content-Type: application/json
```

**Request Body**:
```json
{
    "received_by": "Customer Name",
    "notes": "Delivered in perfect condition",
    "photo": "data:image/jpeg;base64,... (optional)"
}
```

### Add Fulfilled Item

```http
POST /delivery-notes/{id}/fulfilled-items/
Content-Type: application/json
```

**Request Body**:
```json
{
    "invoice_item": 1,
    "delivered_quantity": 5,
    "condition": "perfect",
    "notes": "Delivered without damage"
}
```

### Get Fulfillment Summary

```http
GET /invoices/{invoice_id}/fulfillment-summary/
```

**Response (200 OK)**:
```json
{
    "fulfillment_status": "partially_delivered",
    "items_not_delivered": 2,
    "items_partially_delivered": 1,
    "items_fully_delivered": 3,
    "total_fulfilled_value": "3000.00",
    "fulfillment_percentage": 75.5,
    "delivery_notes": [
        {
            "id": 1,
            "delivery_note_number": "POD0001-260305",
            "status": "delivered",
            "delivery_date": "2026-03-05"
        }
    ]
}
```

---

## Payment Endpoints

### List Payments

```http
GET /payments/
```

### Record Payment

```http
POST /payments/
Content-Type: application/json
```

**Request Body**:
```json
{
    "invoice": 1,
    "amount": "500.00",
    "payment_method": "bank_transfer",
    "payment_account": 1,
    "reference": "REF-001",
    "payment_date": "2026-03-01"
}
```

### Upload Payment Receipt

```http
POST /payments/{id}/upload-receipt/
Content-Type: multipart/form-data

[multipart data with receipt file]
```

---

## Purchase Order Endpoints

### List Purchase Orders

```http
GET /purchase-orders/
```

**Query Parameters**:
| Parameter | Type |
|-----------|------|
| status | draft, submitted, approved, ordered, received |
| supplier_id | Supplier ID |
| created_after | Date |

### Create Purchase Order

```http
POST /purchase-orders/
Content-Type: application/json
```

**Request Body**:
```json
{
    "supplier": 1,
    "branch": 2,
    "expected_delivery": "2026-03-15",
    "delivery_instructions": "Deliver to warehouse",
    "items": [
        {
            "product_id": 100,
            "name": "Item A",
            "quantity": 10,
            "unit_price": "50.00"
        }
    ]
}
```

### Submit for Approval

```http
POST /purchase-orders/{id}/submit/
```

### Approve Purchase Order

```http
POST /purchase-orders/{id}/approve/
Content-Type: application/json
```

**Request Body**:
```json
{
    "approved_budget": "500.00"
}
```

### Mark as Received

```http
POST /purchase-orders/{id}/mark-received/
Content-Type: application/json
```

**Request Body**:
```json
{
    "received_date": "2026-03-10",
    "notes": "All items received"
}
```

---

## Common Patterns

### Pagination

All list endpoints support pagination:

```
GET /invoices/?page=2&page_size=20
```

**Response includes**:
```json
{
    "count": 150,
    "next": "https://.../api/invoices/?page=3",
    "previous": "https://.../api/invoices/?page=1",
    "results": [...]
}
```

### Filtering

Filter using query parameters:

```
GET /invoices/?status=draft&customer_id=5
```

### Searching

Search with the `search` parameter:

```
GET /invoices/?search=INV0001
```

### Sorting

Sort using the `ordering` parameter:

```
GET /invoices/?ordering=-invoice_date,total
```

(Use `-` prefix for descending order)

---

## Error Handling

### Standard Error Response

```json
{
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "One or more fields are invalid",
        "details": {
            "customer": ["This field is required"],
            "items": ["At least one item is required"]
        }
    }
}
```

### Common Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| AUTHENTICATION_REQUIRED | 401 | Missing or invalid token |
| PERMISSION_DENIED | 403 | User lacks permissions |
| NOT_FOUND | 404 | Resource not found |
| VALIDATION_ERROR | 400 | Invalid input data |
| INVALID_STATE_TRANSITION | 400 | Cannot transition to requested state |
| CONFLICT | 409 | Resource already exists or state conflict |
| INTERNAL_ERROR | 500 | Server error |

### 400 Bad Request

```json
{
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "Invoice must have at least one item"
    }
}
```

### 401 Unauthorized

```json
{
    "error": {
        "code": "AUTHENTICATION_REQUIRED",
        "message": "Invalid or missing authentication token"
    }
}
```

### 403 Forbidden

```json
{
    "error": {
        "code": "PERMISSION_DENIED",
        "message": "You do not have permission to perform this action"
    }
}
```

### 404 Not Found

```json
{
    "error": {
        "code": "NOT_FOUND",
        "message": "Invoice with ID 999 not found"
    }
}
```

### 409 Conflict

```json
{
    "error": {
        "code": "INVALID_STATE_TRANSITION",
        "message": "Cannot mark paid invoice as draft",
        "current_state": "paid",
        "requested_state": "draft"
    }
}
```

### 500 Internal Server Error

```json
{
    "error": {
        "code": "INTERNAL_ERROR",
        "message": "An unexpected error occurred. Please contact support.",
        "error_id": "ERR-202603011030-ABC123"
    }
}
```

---

## Rate Limiting

### Headers
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1614556200
```

### Rate Limits
- Standard endpoints: 1000 requests/hour
- Sensitive endpoints (login, payment): 10 requests/minute
- File upload: 100 MB/hour

### When Limited (429 Too Many Requests)
```json
{
    "error": {
        "code": "RATE_LIMIT_EXCEEDED",
        "message": "Too many requests. Try again in 60 seconds",
        "retry_after": 60
    }
}
```

---

## Webhooks (Future)

Planned webhook support for:
- invoice.created
- invoice.sent
- invoice.paid
- delivery.created
- delivery.completed
- payment.received

---

**Document Version**: 1.0  
**Last Updated**: 2026-03-01  
**API Version**: v1  
**Status**: Ready for Use
