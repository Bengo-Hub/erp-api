# ERP Service - Apache Superset Integration

## Overview

The ERP service integrates with the centralized Apache Superset instance for BI dashboards, analytics, and reporting. Superset is deployed as a centralized service accessible to all BengoBox services.

---

## Architecture

### Service Configuration

**Environment Variables**:
- `SUPERSET_BASE_URL` - Superset service URL
- `SUPERSET_ADMIN_USERNAME` - Admin username (K8s secret)
- `SUPERSET_ADMIN_PASSWORD` - Admin password (K8s secret)
- `SUPERSET_API_VERSION` - API version (default: v1)

**Authentication**:
- Admin credentials used for backend-to-Superset communication
- User authentication via JWT tokens passed to Superset for SSO
- Guest tokens generated for embedded dashboards

---

## Integration Methods

### 1. REST API Client

Backend uses Python HTTP client (requests library) configured for Superset REST API calls.

**Base Configuration**:
- Base URL: `SUPERSET_BASE_URL/api/v1`
- Default headers: `Content-Type: application/json`
- Authentication: Bearer token from Superset login endpoint
- Retry policy: Exponential backoff (3 retries)
- Circuit breaker: Opens after 5 consecutive failures

**Key API Endpoints**:

**Authentication**:
- `POST /api/v1/security/login` - Login with admin credentials
- `POST /api/v1/security/refresh` - Refresh access token
- `POST /api/v1/security/guest_token/` - Generate guest token for embedding

**Data Sources**:
- `GET /api/v1/database/` - List all data sources
- `POST /api/v1/database/` - Create new data source
- `PUT /api/v1/database/{id}` - Update data source

**Dashboards**:
- `GET /api/v1/dashboard/` - List all dashboards
- `POST /api/v1/dashboard/` - Create new dashboard
- `GET /api/v1/dashboard/{id}` - Get dashboard details

### 2. Database Direct Connection

Superset connects directly to PostgreSQL database via read-only user for data access.

**Connection Configuration**:
- Database type: PostgreSQL 16+
- Connection string: Provided to Superset via data source API
- Read-only user: `superset_readonly` (created in PostgreSQL)
- Permissions: SELECT only on all tables, no write access
- SSL: Required for production connections

**Read-Only User Setup**:
- Create `superset_readonly` role in PostgreSQL
- Grant CONNECT on database
- Grant USAGE on schema
- Grant SELECT on all tables
- Set default privileges for future tables

**Connection String** (for Superset):
```
postgresql://superset_readonly:password@postgresql.infra.svc.cluster.local:5432/erp_db?sslmode=require
```

**Data Source Creation**:
- Data source created programmatically on application startup
- Connection tested before marking as active
- Data source updated if connection parameters change

---

## Pre-Built Dashboards

### 1. Financial Dashboard

**Charts**:
- Total revenue (metric)
- Total expenses (metric)
- Profit margin (metric)
- Revenue trends (line chart)
- Expense breakdown (pie chart)
- Cash flow trends (line chart)
- Top customers by revenue (bar chart)
- Top vendors by expenses (bar chart)

**Filters**:
- Date range
- Business/branch selection
- Account type

**Data Source**: `invoices`, `bills`, `payments`, `expenses` tables

### 2. HRM Dashboard

**Charts**:
- Total employees (metric)
- Active employees (metric)
- Average salary (metric)
- Employee distribution by department (pie chart)
- Attendance trends (line chart)
- Leave utilization (bar chart)
- Payroll summary (table)
- Performance ratings (bar chart)

**Filters**:
- Date range
- Department selection
- Employee status

**Data Source**: `employees`, `payroll_records`, `attendance_records`, `leave_requests` tables

### 3. Sales & CRM Dashboard

**Charts**:
- Total sales (metric)
- Active leads (metric)
- Conversion rate (metric)
- Sales pipeline (funnel chart)
- Lead sources (pie chart)
- Sales trends (line chart)
- Top sales reps (bar chart)
- Customer lifetime value (line chart)

**Filters**:
- Date range
- Sales rep selection
- Pipeline stage

**Data Source**: `orders`, `leads`, `opportunities`, `contacts` tables

### 4. Inventory Dashboard

**Charts**:
- Total SKUs (metric)
- Low stock items (metric)
- Inventory value (metric)
- Stock movements (line chart)
- Top products by sales (bar chart)
- Stock levels by category (pie chart)
- Reorder alerts (table)
- Inventory turnover (line chart)

**Filters**:
- Date range
- Product category
- Warehouse selection

**Data Source**: `products`, `stock_inventory`, `orders` tables

### 5. Procurement Dashboard

**Charts**:
- Total purchase orders (metric)
- Pending POs (metric)
- Average PO value (metric)
- Purchase trends (line chart)
- Top vendors (bar chart)
- PO status distribution (pie chart)
- Purchase by category (bar chart)
- Vendor performance (table)

**Filters**:
- Date range
- Vendor selection
- PO status

**Data Source**: `purchase_orders`, `purchase_requisitions`, `vendors` tables

### 6. Manufacturing Dashboard

**Charts**:
- Active work orders (metric)
- Production efficiency (metric)
- Quality pass rate (metric)
- Work order completion trends (line chart)
- Production by product (bar chart)
- Quality control results (pie chart)
- Machine utilization (line chart)
- BOM cost analysis (table)

**Filters**:
- Date range
- Product selection
- Work order status

**Data Source**: `work_orders`, `bom_items`, `quality_controls` tables

### 7. Asset Management Dashboard

**Charts**:
- Total assets (metric)
- Asset value (metric)
- Depreciation this month (metric)
- Asset distribution by category (pie chart)
- Asset value trends (line chart)
- Maintenance schedule (table)
- Asset utilization (bar chart)
- Depreciation schedule (line chart)

**Filters**:
- Date range
- Asset category
- Asset status

**Data Source**: `assets`, `asset_depreciations`, `asset_maintenance` tables

---

## Implementation Details

### Initialization Process

1. Authenticate with Superset using admin credentials
2. Create/update data source pointing to PostgreSQL
3. Create/update dashboards for each module:
   - Financial Dashboard
   - HRM Dashboard
   - Sales & CRM Dashboard
   - Inventory Dashboard
   - Procurement Dashboard
   - Manufacturing Dashboard
   - Asset Management Dashboard
4. Log warnings for dashboard creation failures (non-blocking)

### Dashboard Bootstrap

**Backend Endpoint**: `GET /api/v1/dashboards/{module}/embed`

**Process**:
1. Extract tenant ID from context
2. Get dashboard ID for module from Superset
3. Generate guest token with Row-Level Security (RLS) clause filtering by tenant_id
4. Construct embed URL with dashboard ID and guest token
5. Return embed URL with expiration time (5 minutes)

### Row-Level Security (RLS)

**Implementation**:
- Guest tokens include RLS clauses
- RLS filters data by `tenant_id`
- Each tenant sees only their data

---

## Error Handling

### Retry Logic

**Retry Policy**:
- Maximum 3 retry attempts
- Exponential backoff (1s, 2s, 4s delays)
- Retry on 5xx errors or network failures
- Return response on success or after max retries

### Circuit Breaker

**Implementation**:
- Opens after 5 consecutive failures
- Half-open after 60 seconds
- Closes on successful request

### Fallback Strategies

**Superset Unavailable**:
- Return cached dashboard URLs (if available)
- Show static dashboard images
- Log error for monitoring
- Alert operations team

---

## Monitoring

### Metrics

**Integration-Specific Metrics**:
- Superset API call latency (p50, p95, p99)
- Dashboard creation/update success rates
- Guest token generation latency
- Data source connection health

**Prometheus Metrics**:
- `superset_api_call_duration_seconds` - Histogram of API call durations (labeled by endpoint, status)
- `superset_dashboard_views_total` - Counter of dashboard views (labeled by dashboard, tenant)

### Alerts

**Alert Conditions**:
- Superset service unavailability
- High API call failure rate (>5%)
- Dashboard creation failures
- Data source connection failures

---

## Security Considerations

### Authentication & Authorization

- Admin credentials stored in K8s secrets
- Guest tokens expire after 5 minutes
- RLS ensures tenant data isolation
- JWT tokens validated for SSO

### Data Privacy

- Read-only database user
- RLS filters enforce tenant isolation
- Sensitive financial data masked in logs
- PII data excluded from dashboards (if applicable)

---

## References

- [Apache Superset REST API Documentation](https://superset.apache.org/docs/api)
- [Superset Deployment Guide](../../devops-k8s/docs/superset-deployment.md)
- [Cafe Superset Integration](../Cafe/cafe-backend/docs/superset-integration.md)

