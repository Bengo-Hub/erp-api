# ERP Service - Procurement Module Entity Relationship Diagram

The Procurement module manages purchase requisitions, purchase orders, vendor management, and supplier performance.

> **Conventions**
> - UUID primary keys (Django uses auto-incrementing integers by default).
> - `tenant_id` (via `business_id` and `branch_id`) on all operational tables for multi-tenant isolation.
> - Timestamps are `TIMESTAMPTZ` with timezone awareness.
> - Monetary values use `DECIMAL(14,2)` or `DECIMAL(15,2)` with decimal precision.
> - All tables include `created_at` and `updated_at` timestamps.

---

## Purchase Requisitions

### procurement_requests

**Purpose**: Purchase requisition requests from departments.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Requisition identifier |
| `reference_number` | VARCHAR(20) | UNIQUE | Requisition reference number |
| `requester_id` | INTEGER | FK → auth_users(id) | Requester (references auth-service) |
| `request_type` | VARCHAR(20) | CHECK | inventory, external_item, service |
| `purpose` | TEXT | NOT NULL | Purpose of request |
| `priority` | VARCHAR(20) | CHECK | low, medium, high, critical |
| `required_by_date` | DATE | NOT NULL | Required by date |
| `status` | VARCHAR(20) | CHECK | draft, submitted, procurement_review, approved, rejected, ordered, completed |
| `notes` | TEXT | | Additional notes |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_procurement_request_ref` ON `reference_number`
- `idx_proc_request_user` ON `requester_id`
- `idx_proc_request_type` ON `request_type`
- `idx_proc_request_priority` ON `priority`
- `idx_proc_request_required` ON `required_by_date`
- `idx_procurement_request_status` ON `status`

**Relations**:
- `requester_id` → `auth_users(id)` (references auth-service)

### request_items

**Purpose**: Items requested in a procurement request.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Request item identifier |
| `procurement_request_id` | INTEGER | FK → procurement_requests(id) | Requisition reference |
| `stock_item_id` | INTEGER | FK → stock_inventory(id) | Stock item reference (if inventory item) |
| `item_description` | TEXT | | Item description |
| `quantity` | DECIMAL(14,4) | DEFAULT 0.00 | Quantity requested |
| `unit_price` | DECIMAL(14,2) | DEFAULT 0.00 | Unit price estimate |
| `total_price` | DECIMAL(14,2) | DEFAULT 0.00 | Total price estimate |
| `notes` | TEXT | | Item notes |

**Indexes**:
- `idx_request_item_request` ON `procurement_request_id`
- `idx_request_item_stock` ON `stock_item_id`

**Relations**:
- `procurement_request_id` → `procurement_requests(id)`
- `stock_item_id` → `stock_inventory(id)` (references inventory-service)

---

## Purchase Orders

### purchase_orders

**Purpose**: Purchase orders created from requisitions.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Purchase order identifier |
| `order_number` | VARCHAR(50) | UNIQUE | PO number |
| `requisition_id` | INTEGER | FK → procurement_requests(id), UNIQUE | Requisition reference (OneToOne) |
| `vendor_id` | INTEGER | FK → contacts(id) | Vendor contact reference |
| `business_id` | INTEGER | FK → businesses(id) | Business/tenant reference |
| `branch_id` | INTEGER | FK → branches(id) | Branch reference |
| `status` | VARCHAR(20) | CHECK | draft, approved, ordered, received, cancelled |
| `approved_budget` | DECIMAL(15,2) | | Approved budget |
| `actual_cost` | DECIMAL(15,2) | | Actual cost after receiving |
| `delivery_instructions` | TEXT | | Delivery instructions |
| `expected_delivery` | DATE | | Expected delivery date |
| `approved_at` | TIMESTAMPTZ | | Approval timestamp |
| `ordered_at` | TIMESTAMPTZ | | Order placed timestamp |
| `received_at` | TIMESTAMPTZ | | Received timestamp |
| `approved_by_id` | INTEGER | FK → auth_users(id) | Approver (references auth-service) |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_purchase_order_number` ON `order_number`
- `idx_purchase_order_requisition` ON `requisition_id`
- `idx_purchase_order_vendor` ON `vendor_id`
- `idx_purchase_order_status` ON `status`
- `idx_purchase_order_expected_delivery` ON `expected_delivery`

**Relations**:
- `requisition_id` → `procurement_requests(id)` (OneToOne)
- `vendor_id` → `contacts(id)` (where contact_type = 'Suppliers')
- `approved_by_id` → `auth_users(id)` (references auth-service)

**Integration Points**:
- When PO is received → Publish `erp.purchase_order.received` event → treasury-app creates bill, inventory-service updates stock

### purchase_order_items

**Purpose**: Line items in a purchase order.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | PO item identifier |
| `purchase_order_id` | INTEGER | FK → purchase_orders(id) | PO reference |
| `stock_item_id` | INTEGER | FK → stock_inventory(id) | Stock item reference |
| `item_description` | TEXT | | Item description |
| `quantity` | DECIMAL(14,4) | DEFAULT 0.00 | Quantity ordered |
| `unit_price` | DECIMAL(14,2) | DEFAULT 0.00 | Unit price |
| `total_price` | DECIMAL(14,2) | DEFAULT 0.00 | Total price |
| `received_quantity` | DECIMAL(14,4) | DEFAULT 0.00 | Quantity received |

**Indexes**:
- `idx_po_item_po` ON `purchase_order_id`
- `idx_po_item_stock` ON `stock_item_id`

**Relations**:
- `purchase_order_id` → `purchase_orders(id)`
- `stock_item_id` → `stock_inventory(id)` (references inventory-service)

---

## Purchases

### purchases

**Purpose**: Purchase records (goods received).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Purchase identifier |
| `purchase_number` | VARCHAR(50) | UNIQUE | Purchase number |
| `vendor_id` | INTEGER | FK → contacts(id) | Vendor contact reference |
| `purchase_order_id` | INTEGER | FK → purchase_orders(id) | PO reference (optional) |
| `business_id` | INTEGER | FK → businesses(id) | Business/tenant reference |
| `branch_id` | INTEGER | FK → branches(id) | Branch reference |
| `purchase_date` | DATE | | Purchase date |
| `total_amount` | DECIMAL(14,2) | DEFAULT 0.00 | Total amount |
| `status` | VARCHAR(20) | CHECK | draft, received, cancelled |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_purchase_number` ON `purchase_number`
- `idx_purchase_vendor` ON `vendor_id`
- `idx_purchase_po` ON `purchase_order_id`
- `idx_purchase_date` ON `purchase_date`

**Relations**:
- `vendor_id` → `contacts(id)` (where contact_type = 'Suppliers')
- `purchase_order_id` → `purchase_orders(id)`

### purchase_items

**Purpose**: Items in a purchase.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Purchase item identifier |
| `purchase_id` | INTEGER | FK → purchases(id) | Purchase reference |
| `stock_item_id` | INTEGER | FK → stock_inventory(id) | Stock item reference |
| `quantity` | DECIMAL(14,4) | DEFAULT 0.00 | Quantity purchased |
| `unit_price` | DECIMAL(14,2) | DEFAULT 0.00 | Unit price |
| `total_price` | DECIMAL(14,2) | DEFAULT 0.00 | Total price |

**Indexes**:
- `idx_purchase_item_purchase` ON `purchase_id`
- `idx_purchase_item_stock` ON `stock_item_id`

**Relations**:
- `purchase_id` → `purchases(id)`
- `stock_item_id` → `stock_inventory(id)` (references inventory-service)

---

## Supplier Performance

### supplier_performance

**Purpose**: Supplier performance metrics and tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Performance record identifier |
| `vendor_id` | INTEGER | FK → contacts(id) | Vendor contact reference |
| `period_start` | DATE | | Period start date |
| `period_end` | DATE | | Period end date |
| `total_orders` | INTEGER | DEFAULT 0 | Total orders |
| `on_time_delivery_rate` | DECIMAL(5,2) | DEFAULT 0.00 | On-time delivery rate (%) |
| `quality_score` | DECIMAL(5,2) | DEFAULT 0.00 | Quality score (0-100) |
| `average_delivery_time` | INTEGER | DEFAULT 0 | Average delivery time (days) |
| `total_spend` | DECIMAL(14,2) | DEFAULT 0.00 | Total spend |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_supplier_performance_vendor` ON `vendor_id`
- `idx_supplier_performance_period` ON `period_start`, `period_end`

**Relations**:
- `vendor_id` → `contacts(id)` (where contact_type = 'Suppliers')

---

## Contracts

### contracts

**Purpose**: Vendor contracts and agreements.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Contract identifier |
| `contract_number` | VARCHAR(50) | UNIQUE | Contract number |
| `vendor_id` | INTEGER | FK → contacts(id) | Vendor contact reference |
| `contract_type` | VARCHAR(50) | | Contract type |
| `start_date` | DATE | | Contract start date |
| `end_date` | DATE | | Contract end date |
| `total_value` | DECIMAL(14,2) | DEFAULT 0.00 | Total contract value |
| `status` | VARCHAR(20) | CHECK | draft, active, expired, terminated |
| `terms` | TEXT | | Contract terms |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_contract_number` ON `contract_number`
- `idx_contract_vendor` ON `vendor_id`
- `idx_contract_status` ON `status`
- `idx_contract_dates` ON `start_date`, `end_date`

**Relations**:
- `vendor_id` → `contacts(id)` (where contact_type = 'Suppliers')

---

## Integration Points

### External Service References

**Auth Service**:
- `procurement_requests.requester_id` → `auth_users(id)` (requester)
- `purchase_orders.approved_by_id` → `auth_users(id)` (approver)

**Treasury Service**:
- When `purchase_orders.status` = "received" → Publish `erp.purchase_order.received` event → treasury-app creates bill
- Purchase payments → Handled by treasury-app

**Inventory Service**:
- `request_items.stock_item_id` → `stock_inventory(id)` (references inventory-service)
- `purchase_order_items.stock_item_id` → `stock_inventory(id)` (references inventory-service)
- When PO is received → Publish `erp.purchase_order.received` event → inventory-service updates stock levels

**Notifications Service**:
- PO notifications → Publish `erp.purchase_order.created` event
- Approval requests → Publish `erp.procurement_request.submitted` event

---

## Views & Functions

### Recommended Views

**v_procurement_requisition_summary**:
- Requisition details with items and status

**v_procurement_order_summary**:
- PO details with items, vendor, and status

**v_supplier_performance_summary**:
- Supplier performance metrics aggregated

---

## Maintenance Notes

- Maintain this document alongside Django model changes.
- After changing Django models, run migrations and refresh the ERD.
- Financial transactions (bills, payments) are managed by treasury-app - do not duplicate financial logic.
- Inventory management is handled by inventory-service - reference stock items only.
- User management is handled by auth-service - reference user IDs only.

