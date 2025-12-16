# ERP Service - Manufacturing Module Entity Relationship Diagram

The Manufacturing module manages work orders, bill of materials (BOM), production batches, quality control, and manufacturing analytics.

> **Conventions**
> - UUID primary keys (Django uses auto-incrementing integers by default).
> - `tenant_id` (via `business_id` and `branch_id`) on all operational tables for multi-tenant isolation.
> - Timestamps are `TIMESTAMPTZ` with timezone awareness.
> - Monetary values use `DECIMAL(14,2)` or `DECIMAL(15,2)` with decimal precision.
> - Quantity values use `DECIMAL(14,4)` for precision.
> - All tables include `created_at` and `updated_at` timestamps.

---

## Bill of Materials (BOM)

### product_formulas

**Purpose**: Product formulas (BOM) for manufacturing products from raw materials.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Formula identifier |
| `name` | VARCHAR(255) | NOT NULL | Formula name |
| `description` | TEXT | | Description |
| `final_product_id` | INTEGER | FK → products(id) | Final product reference |
| `expected_output_quantity` | DECIMAL(14,4) | | Expected output quantity |
| `output_unit_id` | INTEGER | FK → units(id) | Output unit reference |
| `is_active` | BOOLEAN | DEFAULT true | Active flag |
| `created_by_id` | INTEGER | FK → auth_users(id) | Creator (references auth-service) |
| `version` | INTEGER | DEFAULT 1 | Formula version |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_product_formula_name` ON `name`
- `idx_product_formula_final_prod` ON `final_product_id`
- `idx_product_formula_is_active` ON `is_active`
- `idx_product_formula_version` ON `version`
- UNIQUE(`name`, `version`)

**Relations**:
- `final_product_id` → `products(id)` (from ecommerce.product)
- `output_unit_id` → `units(id)` (from ecommerce.stockinventory)
- `created_by_id` → `auth_users(id)` (references auth-service)

### formula_ingredients

**Purpose**: Raw materials/ingredients in a product formula.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Ingredient identifier |
| `formula_id` | INTEGER | FK → product_formulas(id) | Formula reference |
| `raw_material_id` | INTEGER | FK → stock_inventory(id) | Raw material reference |
| `quantity_required` | DECIMAL(14,4) | DEFAULT 0.00 | Quantity required |
| `unit_id` | INTEGER | FK → units(id) | Unit reference |
| `wastage_percentage` | DECIMAL(5,2) | DEFAULT 0.00 | Wastage percentage |
| `cost_per_unit` | DECIMAL(14,2) | DEFAULT 0.00 | Cost per unit |
| `notes` | TEXT | | Ingredient notes |

**Indexes**:
- `idx_formula_ingredient_formula` ON `formula_id`
- `idx_formula_ingredient_raw_mat` ON `raw_material_id`

**Relations**:
- `formula_id` → `product_formulas(id)`
- `raw_material_id` → `stock_inventory(id)` (references inventory-service)
- `unit_id` → `units(id)` (from ecommerce.stockinventory)

---

## Production Batches

### production_batches

**Purpose**: Production batch/work order tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Batch identifier |
| `batch_number` | VARCHAR(50) | UNIQUE | Batch number |
| `formula_id` | INTEGER | FK → product_formulas(id) | Formula reference |
| `final_product_id` | INTEGER | FK → products(id) | Final product reference |
| `branch_id` | INTEGER | FK → branches(id) | Branch reference |
| `status` | VARCHAR(20) | CHECK | planned, in_progress, completed, cancelled, quality_check |
| `planned_quantity` | DECIMAL(14,4) | DEFAULT 0.00 | Planned quantity |
| `actual_quantity` | DECIMAL(14,4) | DEFAULT 0.00 | Actual quantity produced |
| `start_date` | TIMESTAMPTZ | | Production start date |
| `end_date` | TIMESTAMPTZ | | Production end date |
| `completed_at` | TIMESTAMPTZ | | Completion timestamp |
| `supervisor_id` | INTEGER | FK → auth_users(id) | Supervisor (references auth-service) |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_production_batch_number` ON `batch_number`
- `idx_production_batch_formula` ON `formula_id`
- `idx_production_batch_final_prod` ON `final_product_id`
- `idx_production_batch_status` ON `status`
- `idx_production_batch_start_date` ON `start_date`

**Relations**:
- `formula_id` → `product_formulas(id)`
- `final_product_id` → `products(id)` (from ecommerce.product)
- `branch_id` → `branches(id)`
- `supervisor_id` → `auth_users(id)` (references auth-service)

**Integration Points**:
- When batch is completed → Publish `erp.work_order.completed` event → inventory-service updates finished goods stock

### batch_raw_materials

**Purpose**: Raw materials consumed in a production batch.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Batch material identifier |
| `batch_id` | INTEGER | FK → production_batches(id) | Batch reference |
| `raw_material_id` | INTEGER | FK → stock_inventory(id) | Raw material reference |
| `planned_quantity` | DECIMAL(14,4) | DEFAULT 0.00 | Planned quantity |
| `actual_quantity` | DECIMAL(14,4) | DEFAULT 0.00 | Actual quantity used |
| `unit_id` | INTEGER | FK → units(id) | Unit reference |
| `cost_per_unit` | DECIMAL(14,2) | DEFAULT 0.00 | Cost per unit |
| `total_cost` | DECIMAL(14,2) | DEFAULT 0.00 | Total cost |

**Indexes**:
- `idx_batch_raw_mat_batch` ON `batch_id`
- `idx_batch_raw_mat_raw_mat` ON `raw_material_id`

**Relations**:
- `batch_id` → `production_batches(id)`
- `raw_material_id` → `stock_inventory(id)` (references inventory-service)
- `unit_id` → `units(id)` (from ecommerce.stockinventory)

**Integration Points**:
- When batch starts → Publish `erp.work_order.started` event → inventory-service consumes raw materials

---

## Raw Material Usage

### raw_material_usages

**Purpose**: Raw material usage tracking for production, testing, wastage, returns, and adjustments.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Usage identifier |
| `finished_product_id` | INTEGER | FK → products(id) | Finished product reference |
| `raw_material_id` | INTEGER | FK → stock_inventory(id) | Raw material reference |
| `quantity_used` | DECIMAL(14,4) | DEFAULT 0.00 | Quantity used |
| `transaction_type` | VARCHAR(20) | CHECK | production, testing, wastage, return, adjustment |
| `transaction_date` | TIMESTAMPTZ | DEFAULT NOW() | Transaction date |
| `notes` | TEXT | | Transaction notes |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

**Indexes**:
- `idx_raw_mat_usage_finished` ON `finished_product_id`
- `idx_raw_mat_usage_raw_mat` ON `raw_material_id`
- `idx_raw_mat_usage_txn_type` ON `transaction_type`
- `idx_raw_mat_usage_txn_date` ON `transaction_date`
- UNIQUE(`finished_product_id`, `raw_material_id`, `transaction_date`)

**Relations**:
- `finished_product_id` → `products(id)` (from ecommerce.product)
- `raw_material_id` → `stock_inventory(id)` (references inventory-service)

---

## Quality Control

### quality_checks

**Purpose**: Quality control inspections and checks.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | QC record identifier |
| `batch_id` | INTEGER | FK → production_batches(id) | Batch reference |
| `check_type` | VARCHAR(50) | | Check type |
| `check_date` | TIMESTAMPTZ | DEFAULT NOW() | Check date |
| `inspector_id` | INTEGER | FK → auth_users(id) | Inspector (references auth-service) |
| `status` | VARCHAR(20) | CHECK | passed, failed, pending |
| `notes` | TEXT | | QC notes |
| `defect_count` | INTEGER | DEFAULT 0 | Defect count |
| `sample_size` | INTEGER | DEFAULT 0 | Sample size |
| `pass_rate` | DECIMAL(5,2) | DEFAULT 0.00 | Pass rate (%) |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_quality_check_batch` ON `batch_id`
- `idx_quality_check_type` ON `check_type`
- `idx_quality_check_status` ON `status`
- `idx_quality_check_date` ON `check_date`

**Relations**:
- `batch_id` → `production_batches(id)`
- `inspector_id` → `auth_users(id)` (references auth-service)

---

## Manufacturing Analytics

### manufacturing_analytics

**Purpose**: Manufacturing performance metrics and analytics.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Analytics record identifier |
| `batch_id` | INTEGER | FK → production_batches(id) | Batch reference |
| `formula_id` | INTEGER | FK → product_formulas(id) | Formula reference |
| `production_efficiency` | DECIMAL(5,2) | DEFAULT 0.00 | Production efficiency (%) |
| `material_utilization` | DECIMAL(5,2) | DEFAULT 0.00 | Material utilization (%) |
| `wastage_percentage` | DECIMAL(5,2) | DEFAULT 0.00 | Wastage percentage |
| `labor_hours` | DECIMAL(5,2) | DEFAULT 0.00 | Labor hours |
| `machine_hours` | DECIMAL(5,2) | DEFAULT 0.00 | Machine hours |
| `total_cost` | DECIMAL(14,2) | DEFAULT 0.00 | Total production cost |
| `cost_per_unit` | DECIMAL(14,2) | DEFAULT 0.00 | Cost per unit |
| `quality_score` | DECIMAL(5,2) | DEFAULT 0.00 | Quality score (0-100) |
| `period_start` | DATE | | Period start date |
| `period_end` | DATE | | Period end date |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_manufacturing_analytics_batch` ON `batch_id`
- `idx_manufacturing_analytics_formula` ON `formula_id`
- `idx_manufacturing_analytics_period` ON `period_start`, `period_end`

**Relations**:
- `batch_id` → `production_batches(id)`
- `formula_id` → `product_formulas(id)`

---

## Integration Points

### External Service References

**Auth Service**:
- `product_formulas.created_by_id` → `auth_users(id)` (creator)
- `production_batches.supervisor_id` → `auth_users(id)` (supervisor)
- `quality_checks.inspector_id` → `auth_users(id)` (inspector)

**Inventory Service**:
- `formula_ingredients.raw_material_id` → `stock_inventory(id)` (references inventory-service)
- `batch_raw_materials.raw_material_id` → `stock_inventory(id)` (references inventory-service)
- `raw_material_usages.raw_material_id` → `stock_inventory(id)` (references inventory-service)
- When batch starts → Publish `erp.work_order.started` event → inventory-service consumes raw materials
- When batch completes → Publish `erp.work_order.completed` event → inventory-service updates finished goods stock

**IoT Service**:
- Production line monitoring → Consume `iot.telemetry.received` events
- Device alerts → Consume `iot.alert.triggered` events

**Notifications Service**:
- Work order notifications → Publish `erp.work_order.completed` event
- Quality check alerts → Publish `erp.quality_check.failed` event

---

## Views & Functions

### Recommended Views

**v_manufacturing_batch_summary**:
- Batch details with materials, costs, and quality metrics

**v_manufacturing_formula_cost**:
- Formula cost analysis with raw material costs

**v_manufacturing_analytics_summary**:
- Manufacturing performance metrics aggregated by period

---

## Maintenance Notes

- Maintain this document alongside Django model changes.
- After changing Django models, run migrations and refresh the ERD.
- Inventory management is handled by inventory-service - reference stock items only.
- User management is handled by auth-service - reference user IDs only.

