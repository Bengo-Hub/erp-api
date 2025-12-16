# ERP Service - Implementation Plan

## Executive Summary

**System Purpose**: Enterprise Resource Planning (ERP) system for BengoBox, providing integrated business management across **CRM, HRM, Procurement, Manufacturing, and E-commerce**. The ERP service focuses on these core domains and integrates with specialized microservices (treasury-app, inventory-service, auth-service, notifications-service) for financial, inventory, authentication, and notification capabilities.

**Key Capabilities**:
- **Customer Relationship Management (CRM)**: Contacts, leads, opportunities, sales pipeline, campaigns
- **Human Resource Management (HRM)**: Employees, payroll, attendance, leave, recruitment, training, performance
- **Procurement**: Purchase requisitions, purchase orders, vendor management, supplier performance
- **Manufacturing**: Work orders, BOM, production planning, quality control
- **E-commerce**: Product catalog, orders, cart, POS operations, vendor management

**Entity Ownership**: This service owns ERP-specific entities: CRM (contacts, leads, opportunities, campaigns), HRM (employees, payroll, attendance, leave), Procurement (purchase orders, requisitions, vendors), Manufacturing (work orders, BOM), E-commerce (products, orders, cart, POS). **ERP does NOT own**: users (references auth-service), tenants (references auth-service), financial transactions (references treasury-app), inventory balances (references inventory-service), notifications (references notifications-service).

**Integration Strategy**: ERP integrates with external microservices instead of duplicating logic:
- **Finance/Accounting** → `treasury-app` (invoices, bills, payments, ledger, reconciliation, expenses, taxes)
- **Inventory Management** → `inventory-service` (stock levels, movements, warehouses)
- **Authentication/Authorization** → `auth-service` (SSO, JWT, user management)
- **Notifications** → `notifications-service` (emails, SMS, push notifications)
- **Logistics** → `logistics-service` (shipping, delivery tracking)
- **POS Operations** → `pos-service` (point of sale transactions)

---

## Technology Stack

### Core Framework
- **Language**: Python 3.11+
- **Framework**: Django 4.2+ with Django REST Framework
- **Architecture**: Vertical Slice Architecture with CQRS (MediatR pattern)
- **API Documentation**: drf-spectacular (OpenAPI/Swagger)

### Data & Caching
- **Primary Database**: PostgreSQL 16+
- **ORM**: Django ORM with select_related/prefetch_related optimization
- **Caching**: Redis 7+ for caching, session management
- **Message Broker**: Celery with Redis/RabbitMQ

### Supporting Libraries
- **PDF Generation**: reportlab
- **Excel Export**: openpyxl
- **Data Processing**: Polars (high-performance analytics)
- **Validation**: Django validators + custom validators
- **Logging**: Python logging with structured output
- **Tracing**: OpenTelemetry instrumentation
- **Metrics**: Prometheus client

### DevOps & Observability
- **Containerization**: Multi-stage Docker builds
- **Orchestration**: Kubernetes (via centralized devops-k8s)
- **CI/CD**: GitHub Actions → ArgoCD
- **Monitoring**: Prometheus + Grafana, OpenTelemetry
- **APM**: Jaeger distributed tracing

---

## Domain Modules & Features

### 1. Customer Relationship Management (CRM)

**ERP-Specific Features**:
- Contact management (customers, vendors, partners)
- Lead management (lead capture, qualification, conversion)
- Sales pipeline (opportunities, stages, forecasting)
- Campaign management (marketing campaigns, email campaigns)
- Customer communication history
- Sales reporting and analytics

**Entities Owned**:
- `contacts` - Customer/vendor contacts
- `leads` - Sales leads
- `opportunities` - Sales opportunities
- `pipeline_stages` - Sales pipeline stages
- `campaigns` - Marketing campaigns

**Integration Points**:
- **auth-service**: User identity (references only)
- **notifications-service**: Campaign emails, lead notifications
- **treasury-app**: Invoice generation from opportunities (via API)

**Module ERD**: See `docs/erd/crm.md`

### 2. Human Resource Management (HRM)

**ERP-Specific Features**:
- Employee management (profiles, employment history, documents)
- Payroll processing (salary, allowances, deductions, tax calculations)
- Attendance tracking (shifts, schedules, time tracking)
- Leave management (leave types, requests, approvals, balances)
- Performance management (appraisals, goals, reviews)
- Training and development (training programs, certifications)
- Recruitment (job postings, applications, interviews, offers)
- Employee onboarding and offboarding

**Entities Owned**:
- `employees` - Employee profiles
- `payroll_records` - Payroll processing records
- `attendance_records` - Attendance tracking
- `leave_requests` - Leave management
- `appraisals` - Performance reviews
- `training_programs` - Training management
- `recruitment_jobs` - Job postings
- `recruitment_applications` - Job applications

**Integration Points**:
- **auth-service**: User identity sync (references only)
- **notifications-service**: Payroll notifications, leave approvals
- **treasury-app**: Payroll payments, expense reimbursements (via API)

**Module ERD**: See `docs/erd/hrm.md`

### 3. Procurement

**ERP-Specific Features**:
- Purchase requisitions (requisition creation, approvals)
- Purchase orders (PO creation, vendor management, tracking)
- Vendor management (vendor profiles, performance tracking)
- Receiving and inspection
- Purchase analytics and reporting

**Entities Owned**:
- `purchase_requisitions` - Purchase requests
- `purchase_orders` - Purchase orders
- `purchase_order_items` - PO line items
- `purchase_receipts` - Goods received
- `vendors` - Vendor profiles
- `supplier_performance` - Supplier performance metrics

**Integration Points**:
- **inventory-service**: Stock receipt, inventory updates (via API/events)
- **treasury-app**: Bill creation from POs, payment processing (via API/events)
- **notifications-service**: PO notifications, approval requests

**Module ERD**: See `docs/erd/procurement.md`

### 4. Manufacturing

**ERP-Specific Features**:
- Work order management (work orders, scheduling, tracking)
- Bill of Materials (BOM) management
- Production planning and scheduling
- Quality control (QC inspections, quality reports)
- Manufacturing analytics

**Entities Owned**:
- `work_orders` - Manufacturing work orders
- `bom_items` - Bill of materials
- `production_schedules` - Production planning
- `quality_controls` - QC records

**Integration Points**:
- **inventory-service**: Material consumption, finished goods (via API/events)
- **iot-service**: Production line monitoring (via API/events)
- **notifications-service**: Work order notifications

**Module ERD**: See `docs/erd/manufacturing.md`

### 5. E-commerce

**ERP-Specific Features**:
- Product catalog (products, variants, categories, pricing)
- Order management (orders, order items, order status)
- Shopping cart (cart management, checkout)
- POS (point of sale) operations
- Vendor management (vendor profiles, vendor products)
- E-commerce analytics (sales reports, product performance)

**Entities Owned**:
- `products` - Product catalog
- `product_variants` - Product variants
- `product_categories` - Product categories
- `orders` - Customer orders
- `cart_items` - Shopping cart
- `pos_sessions` - POS sessions
- `vendors` - Vendor profiles

**Integration Points**:
- **inventory-service**: Inventory balances, stock movements (via API/events) - **DO NOT duplicate inventory logic**
- **pos-service**: POS operations (via API/events) - **DO NOT duplicate POS logic**
- **logistics-service**: Order fulfillment (via API/events)
- **treasury-app**: Payment processing (via API/events) - **DO NOT duplicate payment logic**
- **notifications-service**: Order confirmations, shipping notifications

**Module ERD**: See `docs/erd/ecommerce.md`

---

## Removed Modules (Integrated with External Services)

### Finance/Accounting → Treasury Service

**Removed from ERP**: All financial management modules (accounts, expenses, taxes, payment, budgets, cashflow, reconciliation, invoicing, quotations) are now handled by `treasury-app`.

**Integration**: ERP publishes events and calls APIs:
- Invoice creation → `POST /api/v1/treasury/invoices`
- Bill creation → `POST /api/v1/treasury/bills`
- Payment processing → `POST /api/v1/treasury/payments`
- Expense recording → `POST /api/v1/treasury/expenses`

**Events Published**:
- `erp.invoice.required` - When opportunity is won
- `erp.bill.required` - When PO is received
- `erp.payroll.required` - When payroll is processed

### Inventory Management → Inventory Service

**Removed from ERP**: Stock inventory management is now handled by `inventory-service`.

**Integration**: ERP calls APIs for stock levels and movements:
- Stock levels → `GET /api/v1/inventory/items/{id}/stock`
- Stock movements → `POST /api/v1/inventory/movements`
- Stock adjustments → `POST /api/v1/inventory/adjustments`

**Events Published**:
- `erp.order.created` - For inventory reservation
- `erp.purchase_order.received` - For stock receipt
- `erp.work_order.completed` - For finished goods

### Authentication/Authorization → Auth Service

**Removed from ERP**: User management and authentication is now handled by `auth-service`.

**Integration**: ERP uses JWT validation and references user IDs:
- JWT validation → `shared/auth-client` library
- User sync → `GET /api/v1/auth/users/{id}`

### Notifications → Notifications Service

**Removed from ERP**: Notification sending is now handled by `notifications-service`.

**Integration**: ERP publishes events for notifications:
- `erp.invoice.created` → Invoice notification
- `erp.payroll.processed` → Payroll notification
- `erp.leave.requested` → Leave approval notification

---

## Cross-Cutting Concerns

### Testing
- Django test suites with TestCase
- Testcontainers for integration testing
- Mock services for external dependencies
- Performance testing for report generation

### Observability
- Structured logging (Python logging)
- Tracing via OpenTelemetry
- Metrics exported via Prometheus
- Distributed tracing via Tempo/Jaeger

### Security
- OWASP ASVS baseline
- TLS everywhere
- Secrets via Vault/Parameter Store
- Rate limiting & anomaly detection middleware
- JWT validation via auth-service
- Row-level security with tenant_id

### Scalability
- Stateless HTTP layer
- Background workers via Celery
- Database connection pooling
- Caching strategy for frequently accessed data
- Query optimization (select_related/prefetch_related)

### Data Modelling
- Django models as single source of truth
- Tenant/outlet discovery webhooks
- Outbox pattern for reliable domain events
- Database migrations via Django migrations

---

## API & Protocol Strategy

- **REST-first**: Versioned routes (`/api/v1/{module}/`), documented via OpenAPI
- **WebSocket**: Real-time updates (Django Channels)
- **Webhooks**: External provider callbacks, ERP events
- **Idempotency**: Keys, correlation IDs, distributed tracing context propagation

---

## Compliance & Risk Controls

- Align with Kenya Data Protection Act: explicit consent flows, user data export/delete endpoints, audit logging
- Financial compliance: Integration with treasury-app for double-entry bookkeeping, audit trails, financial reporting
- Tax compliance: KRA iTax integration (via treasury-app)
- Disaster recovery playbook, RTO/RPO targets (<1 hour)

---

## Sprint Delivery Plan

See `docs/sprints/` folder for detailed sprint plans:
- Sprint 0: Foundations
- Sprint 1: Core Modules (CRM, HRM)
- Sprint 2: Procurement & Manufacturing
- Sprint 3: E-commerce
- Sprint 4: External Service Integrations
- Sprint 5: Analytics & Reporting
- Sprint 6: Integration & Hardening
- Sprint 7: Launch & Handover

---

## Runtime Ports & Environments

- **Local development**: Service runs on port **8000** (Django default)
- **Cloud deployment**: All backend services listen on **port 4000** for consistency behind ingress controllers

---

## References

- [Integration Guide](docs/integrations.md)
- [Module ERDs](docs/erd/)
  - [CRM ERD](docs/erd/crm.md)
  - [HRM ERD](docs/erd/hrm.md)
  - [Procurement ERD](docs/erd/procurement.md)
  - [Manufacturing ERD](docs/erd/manufacturing.md)
  - [E-commerce ERD](docs/erd/ecommerce.md)
- [Superset Integration](docs/superset-integration.md)
- [Sprint Plans](docs/sprints/)
