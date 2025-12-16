# ERP Service - E-commerce Module Entity Relationship Diagram

The E-commerce module manages product catalog, orders, shopping cart, POS operations, and vendor management. **Note**: Inventory management and POS operations are handled by external services (inventory-service, pos-service).

> **Conventions**
> - UUID primary keys (Django uses auto-incrementing integers by default).
> - `tenant_id` (via `business_id` and `branch_id`) on all operational tables for multi-tenant isolation.
> - Timestamps are `TIMESTAMPTZ` with timezone awareness.
> - Monetary values use `DECIMAL(14,2)` or `DECIMAL(15,2)` with decimal precision.
> - Quantity values use `DECIMAL(14,4)` for precision.
> - All tables include `created_at` and `updated_at` timestamps.

---

## Product Catalog

### categories

**Purpose**: Hierarchical product category structure.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Category identifier |
| `name` | VARCHAR(255) | NOT NULL | Category name |
| `parent_id` | INTEGER | FK → categories(id) | Parent category (self-referential) |
| `display_image` | VARCHAR(255) | | Display image path |
| `status` | VARCHAR(20) | CHECK | active, inactive |
| `level` | INTEGER | DEFAULT 0 | Hierarchy level (0=root, 1=main, 2=sub) |
| `order` | INTEGER | DEFAULT 0 | Display order |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_category_name` ON `name`
- `idx_category_parent` ON `parent_id`
- `idx_category_status` ON `status`
- `idx_category_level` ON `level`

**Relations**:
- `parent_id` → `categories(id)` (self-referential)

### products

**Purpose**: Product catalog (references inventory-service for stock levels).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Product identifier |
| `name` | VARCHAR(255) | NOT NULL | Product name |
| `description` | TEXT | | Product description |
| `category_id` | INTEGER | FK → categories(id) | Category reference |
| `sku` | VARCHAR(100) | UNIQUE | SKU code |
| `barcode` | VARCHAR(100) | | Barcode |
| `status` | VARCHAR(20) | CHECK | active, inactive |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_product_name` ON `name`
- `idx_product_category` ON `category_id`
- `idx_product_sku` ON `sku`
- `idx_product_barcode` ON `barcode`
- `idx_product_status` ON `status`

**Relations**:
- `category_id` → `categories(id)`

**Integration Points**:
- Stock levels → References `inventory-service` via `stock_inventory` table
- When product is updated → Publish `erp.product.updated` event → pos-service syncs catalog

### product_variants

**Purpose**: Product variants (size, color, etc.).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Variant identifier |
| `product_id` | INTEGER | FK → products(id) | Product reference |
| `variant_name` | VARCHAR(255) | | Variant name |
| `sku` | VARCHAR(100) | UNIQUE | Variant SKU |
| `price` | DECIMAL(14,2) | DEFAULT 0.00 | Variant price |
| `status` | VARCHAR(20) | CHECK | active, inactive |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_product_variant_product` ON `product_id`
- `idx_product_variant_sku` ON `sku`
- `idx_product_variant_status` ON `status`

**Relations**:
- `product_id` → `products(id)`

---

## Orders

### ecommerce_orders

**Purpose**: E-commerce customer orders (extends BaseOrder).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Order identifier |
| `order_id` | VARCHAR(50) | UNIQUE | Order ID |
| `order_number` | VARCHAR(50) | UNIQUE | Order number |
| `customer_id` | INTEGER | FK → contacts(id) | Customer contact reference |
| `business_id` | INTEGER | FK → businesses(id) | Business/tenant reference |
| `branch_id` | INTEGER | FK → branches(id) | Branch reference |
| `status` | VARCHAR(20) | CHECK | draft, pending, confirmed, processing, shipped, delivered, cancelled |
| `inventory_reserved` | BOOLEAN | DEFAULT false | Inventory reserved flag |
| `inventory_allocated` | BOOLEAN | DEFAULT false | Inventory allocated flag |
| `inventory_reservation_expires` | TIMESTAMPTZ | | Reservation expiry |
| `backorder_items` | JSONB | | Backordered items |
| `customer_notes` | TEXT | | Customer notes |
| `internal_notes` | TEXT | | Internal notes |
| `cancellation_reason` | TEXT | | Cancellation reason |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_ecommerce_order_id` ON `order_id`
- `idx_ecommerce_order_number` ON `order_number`
- `idx_ecommerce_order_customer` ON `customer_id`
- `idx_ecommerce_order_status` ON `status`
- `idx_ecommerce_order_created_at` ON `created_at`

**Relations**:
- `customer_id` → `contacts(id)` (from CRM module)
- `business_id` → `businesses(id)` (tenant reference)
- `branch_id` → `branches(id)` (outlet reference)

**Integration Points**:
- When order is created → Publish `erp.order.created` event → inventory-service reserves stock
- When order is fulfilled → Publish `erp.order.fulfilled` event → logistics-service creates shipment
- Payment processing → Handled by treasury-app

### order_items

**Purpose**: Line items in an order (extends BaseOrderItem).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Order item identifier |
| `order_id` | INTEGER | FK → ecommerce_orders(id) | Order reference |
| `product_id` | INTEGER | FK → products(id) | Product reference |
| `variant_id` | INTEGER | FK → product_variants(id) | Variant reference (optional) |
| `quantity` | DECIMAL(14,4) | DEFAULT 0.00 | Quantity |
| `unit_price` | DECIMAL(14,2) | DEFAULT 0.00 | Unit price |
| `total_price` | DECIMAL(14,2) | DEFAULT 0.00 | Total price |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

**Indexes**:
- `idx_order_item_order` ON `order_id`
- `idx_order_item_product` ON `product_id`
- `idx_order_item_variant` ON `variant_id`

**Relations**:
- `order_id` → `ecommerce_orders(id)`
- `product_id` → `products(id)`
- `variant_id` → `product_variants(id)`

---

## Shopping Cart

### cart_items

**Purpose**: Shopping cart items.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Cart item identifier |
| `customer_id` | INTEGER | FK → contacts(id) | Customer reference |
| `product_id` | INTEGER | FK → products(id) | Product reference |
| `variant_id` | INTEGER | FK → product_variants(id) | Variant reference (optional) |
| `quantity` | DECIMAL(14,4) | DEFAULT 0.00 | Quantity |
| `unit_price` | DECIMAL(14,2) | DEFAULT 0.00 | Unit price |
| `total_price` | DECIMAL(14,2) | DEFAULT 0.00 | Total price |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_cart_item_customer` ON `customer_id`
- `idx_cart_item_product` ON `product_id`
- `idx_cart_item_variant` ON `variant_id`

**Relations**:
- `customer_id` → `contacts(id)` (from CRM module)
- `product_id` → `products(id)`
- `variant_id` → `product_variants(id)`

---

## POS Operations

**Note**: POS operations are primarily handled by `pos-service`. ERP's e-commerce module manages product catalog that syncs with POS.

### pos_sessions

**Purpose**: POS session tracking (references pos-service).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | POS session identifier |
| `register_id` | INTEGER | FK → registers(id) | Register reference |
| `cashier_id` | INTEGER | FK → auth_users(id) | Cashier (references auth-service) |
| `branch_id` | INTEGER | FK → branches(id) | Branch reference |
| `status` | VARCHAR(20) | CHECK | open, closed |
| `opened_at` | TIMESTAMPTZ | DEFAULT NOW() | Opened timestamp |
| `closed_at` | TIMESTAMPTZ | | Closed timestamp |
| `opening_balance` | DECIMAL(14,2) | DEFAULT 0.00 | Opening balance |
| `closing_balance` | DECIMAL(14,2) | DEFAULT 0.00 | Closing balance |

**Indexes**:
- `idx_pos_session_register` ON `register_id`
- `idx_pos_session_cashier` ON `cashier_id`
- `idx_pos_session_status` ON `status`
- `idx_pos_session_opened_at` ON `opened_at`

**Relations**:
- `register_id` → `registers(id)` (from ecommerce.pos)
- `cashier_id` → `auth_users(id)` (references auth-service)
- `branch_id` → `branches(id)`

**Integration Points**:
- POS orders → Consume `pos.order.created` events from pos-service
- Product catalog sync → Publish `erp.product.updated` events to pos-service

---

## Vendors

### vendors

**Purpose**: Vendor profiles for marketplace/e-commerce vendors.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Vendor identifier |
| `contact_id` | INTEGER | FK → contacts(id) | Contact reference (where contact_type = 'Suppliers') |
| `business_id` | INTEGER | FK → businesses(id) | Business/tenant reference |
| `vendor_code` | VARCHAR(50) | UNIQUE | Vendor code |
| `status` | VARCHAR(20) | CHECK | active, inactive, suspended |
| `rating` | DECIMAL(3,2) | DEFAULT 0.00 | Vendor rating (0-5) |
| `total_sales` | DECIMAL(14,2) | DEFAULT 0.00 | Total sales |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_vendor_contact` ON `contact_id`
- `idx_vendor_code` ON `vendor_code`
- `idx_vendor_status` ON `status`

**Relations**:
- `contact_id` → `contacts(id)` (from CRM module, where contact_type = 'Suppliers')
- `business_id` → `businesses(id)` (tenant reference)

---

## Integration Points

### External Service References

**Auth Service**:
- `pos_sessions.cashier_id` → `auth_users(id)` (cashier)

**Treasury Service**:
- Order payments → Handled by treasury-app
- When order is created → Publish `erp.order.created` event → treasury-app processes payment

**Inventory Service**:
- Stock levels → References `stock_inventory` table (managed by inventory-service)
- When order is created → Publish `erp.order.created` event → inventory-service reserves stock
- Stock movements → Handled by inventory-service

**POS Service**:
- POS operations → Handled by pos-service
- Product catalog sync → Publish `erp.product.updated` events
- POS orders → Consume `pos.order.created` events

**Logistics Service**:
- Order fulfillment → When order is fulfilled, publish `erp.order.fulfilled` event → logistics-service creates shipment
- Shipping tracking → Consume `logistics.shipment.delivered` events

**Notifications Service**:
- Order confirmations → Publish `erp.order.created` event
- Shipping notifications → Consume `logistics.shipment.created` events

**CRM Module**:
- `ecommerce_orders.customer_id` → `contacts(id)` (customer)
- `cart_items.customer_id` → `contacts(id)` (customer)
- `vendors.contact_id` → `contacts(id)` (vendor)

---

## Views & Functions

### Recommended Views

**v_ecommerce_order_summary**:
- Order details with items, customer, and status

**v_ecommerce_product_catalog**:
- Product catalog with categories and variants

**v_ecommerce_sales_summary**:
- Sales metrics by product, category, period

---

## Maintenance Notes

- Maintain this document alongside Django model changes.
- After changing Django models, run migrations and refresh the ERD.
- **Inventory management is handled by inventory-service** - do not duplicate inventory logic. Reference stock items only.
- **POS operations are handled by pos-service** - do not duplicate POS logic. Sync product catalog only.
- **Payment processing is handled by treasury-app** - do not duplicate payment logic.
- User management is handled by auth-service - reference user IDs only.

