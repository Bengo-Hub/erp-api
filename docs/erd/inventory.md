# Inventory Management Module - Comprehensive Audit

## Executive Summary

The Inventory (Stock) module, located in `ecommerce/stockinventory/`, manages product stock levels, movements, valuations, and inventory transactions. It integrates with product management, sales, manufacturing, and procurement modules.

**Module Location**: `ecommerce/stockinventory/`  
**Related Modules**: ecommerce/product, manufacturing, procurement, finance  
**Status**: Functional with critical gaps  
**Coverage**: ~25% test coverage, urgently needs expansion

---

## Database Schema & Models

### Core Models

#### 1. **StockInventory** (ecommerce/stockinventory/models.py)
**Purpose**: Core inventory item tracking

**Key Fields**:
```
- product (ForeignKey to Products) - Required
- product_type (CharField) - single, variable, combo
- variation (ForeignKey to Variations, nullable)
- warranty (ForeignKey to Warranties, nullable)
- discount (ForeignKey to Discounts, nullable)
- applicable_tax (ForeignKey to Tax, nullable)
- buying_price (DecimalField, max_digits=14, decimals=4, default=0)
- selling_price (DecimalField, max_digits=14, decimals=4, default=0)
- profit_margin (DecimalField, max_digits=14, decimals=4, default=0)
- manufacturing_cost (DecimalField, max_digits=14, decimals=4, default=0)
- stock_level (IntegerField, default=1) ⚠️ ISSUE: No transaction tracking
- reorder_level (PositiveIntegerField, default=2)
- unit (ForeignKey to Unit, nullable)
- branch (ForeignKey to Branch, nullable)
- usage (CharField) - EX-UK, Refurbished, Used Like New, Second Hand, New
- supplier (ForeignKey to Contact, nullable)
- availability (CharField) - In Stock, Out of Stock, Re-Order
- is_new_arrival (BooleanField, default=False)
- is_top_pick (BooleanField, default=False)
- is_raw_material (BooleanField, default=False)
- created_at (DateTimeField, auto_now_add=True)
- updated_at (DateTimeField, auto_now=True)
- delete_status (BooleanField, default=False)
```

**Key Characteristics**:
- Each product can have multiple stock entries (per branch, per variation)
- Stock level is denormalized (should be sum of transactions)
- No hard delete (soft delete via delete_status)
- Automatically prevents service-type products from having stock

**Key Methods**:
- `save()` - Validates product type, sets defaults, calculates profit margin
- `create_stock_transaction()` - Creates StockTransaction record
- `suggest_selling_price(profit_margin_percentage)` - Calculates price based on margin

**Index Strategy**:
```
idx_stock_inventory_product
idx_stock_inv_product_type
idx_stock_inventory_variation
idx_stock_inventory_branch
idx_stock_inventory_supplier
idx_stock_inv_availability
idx_stock_inv_new_arrival
idx_stock_inv_top_pick
idx_stock_inv_delete_status
idx_stock_inventory_created_at
```

---

#### 2. **StockTransaction** (ecommerce/stockinventory/models.py)
**Purpose**: Track every stock movement for audit trail

**Key Fields**:
```
- transaction_type (CharField) - INITIAL, PURCHASE, SALE, SALE_RETURN, PURCHASE_RETURN, 
                                 ADJUSTMENT, TRANSFER_IN, TRANSFER_OUT, STOCK_TAKE, PRODUCTION
- stock_item (ForeignKey to StockInventory)
- quantity (DecimalField) - Can be negative for outflow
- notes (TextField, nullable)
- branch (ForeignKey to Branch, nullable)
- transaction_date (DateTimeField)
- reference_number (CharField, nullable) - Links to source document (Invoice#, PO#, etc)
- cost_per_unit (DecimalField, nullable) - For valuation
- created_at (DateTimeField, auto_now_add=True)
```

**Transaction Types**:
- `INITIAL` - Opening/initial stock
- `PURCHASE` - Stock received from supplier
- `SALE` - Stock sold to customer
- `SALE_RETURN` - Customer return
- `PURCHASE_RETURN` - Return to supplier
- `ADJUSTMENT` - Stock count adjustment
- `TRANSFER_IN` - Stock transfer from another branch
- `TRANSFER_OUT` - Stock transfer to another branch
- `STOCK_TAKE` - Physical count reconciliation
- `PRODUCTION` - Stock created via manufacturing

**Critical Issue**:
- ❌ StockInventory.stock_level is NOT automatically updated from transactions
- ❌ Manual sync required between transaction log and stock_level field
- ❌ Can lead to inconsistencies

---

#### 3. **StockTransfer** (ecommerce/stockinventory/models.py)
**Purpose**: Track inter-branch stock transfers

**Key Fields**:
```
- request_number (CharField) - Unique transfer reference
- source_branch (ForeignKey to Branch)
- destination_branch (ForeignKey to Branch)
- transfer_date (DateTimeField)
- delivery_date (DateTimeField, nullable)
- status (CharField) - pending, in_transit, delivered, cancelled
- transferred_by (ForeignKey to User)
- received_by (ForeignKey to User, nullable)
- notes (TextField, nullable)
```

---

#### 4. **StockTransferItem** (ecommerce/stockinventory/models.py)
**Purpose**: Line items in stock transfers

**Key Fields**:
```
- transfer (ForeignKey to StockTransfer)
- stock_item (ForeignKey to StockInventory)
- quantity (DecimalField) - Quantity to transfer
- quantity_received (DecimalField, nullable)
- condition (CharField) - new, minor_damage, major_damage
```

---

#### 5. **StockAdjustment** (ecommerce/stockinventory/models.py)
**Purpose**: Record stock count adjustments

**Key Fields**:
```
- stock_item (ForeignKey to StockInventory)
- adjustment_date (DateTimeField)
- system_quantity (DecimalField) - What system shows
- physical_quantity (DecimalField) - What was actually counted
- difference (DecimalField) - physical - system
- reason (CharField) - theft, breakage, counting_error, found, lost
- notes (TextField, nullable)
- adjusted_by (ForeignKey to User)
- status (CharField) - pending, approved, rejected
```

---

#### 6. **Unit** (ecommerce/stockinventory/models.py)
**Purpose**: Units of measurement

**Key Fields**:
```
- title (CharField) - e.g., "Pieces", "Kg", "Liters", "Meters"
```

**Index**: idx_units_title

---

#### 7. **Variations** (ecommerce/stockinventory/models.py)
**Purpose**: Product variations/SKUs

**Key Fields**:
```
- stock_item (ForeignKey to StockInventory, nullable)
- title (CharField) - Variation name/value
- serial (CharField, unique, nullable) - Serial number
- sku (CharField, unique, nullable) - Stock keeping unit
```

**Relationships**:
- Has many VariationImages
- Referenced by StockInventory

---

#### 8. **Warranties** (ecommerce/stockinventory/models.py)
**Purpose**: Product warranty definitions

**Key Fields**:
```
- name (CharField)
- duration (IntegerField, default=6) - Duration value
- duration_period (CharField) - Days, Months, Years
- description (TextField) - Special terms like IMEI tracking
```

---

#### 9. **Discounts** (ecommerce/stockinventory/models.py)
**Purpose**: Sales discount definitions

**Key Fields**:
```
- name (CharField)
- discount_type (CharField) - Fixed, Percentage
- discount_amount (DecimalField)
- percentage (DecimalField)
- start_date (DateField)
- end_date (DateField)
- priority (IntegerField, default=1) - Order of application
- is_active (BooleanField, default=True)
```

**Auto-Behavior**: If dates not provided, defaults to current date + 30 days

---

#### 10. **Favourites** (ecommerce/stockinventory/models.py)
**Purpose**: User product favorites

**Key Fields**:
```
- user (ForeignKey to User)
- stock (ForeignKey to StockInventory)
```

---

## Serializers

### 1. **StockSerializer** (ecommerce/stockinventory/serializers.py)
**Used for**: Detailed stock view

**Key Fields**:
- All StockInventory fields
- branch (BranchSerializer)
- product (StockProductSerializer)
- supplier (SupplierSerializer)
- variation (VariationSerializer with images)
- total_sales (computed - sum of sales items)

---

### 2. **SingleStockSerializer**
**Used for**: Simplified stock operations

---

### 3. **StockTransactionSerializer**
**Used for**: Transaction log viewing

---

### 4. **StockTransferSerializer**
**Used for**: Inter-branch transfers

---

### 5. **UnitSerializer**
**Fields**: id, title

---

### 6. **VariationSerializer**
**Fields**: id, title, serial, sku, images (VariationImagesSerializer)

---

### 7. **VariantionImagesSerializer**
**Fields**: image URL

---

### 8. **DiscountsSerializer**
**All Fields**: All Discount fields

---

## ViewSets & API Endpoints

### 1. **StockInventoryViewSet**
**Key Actions**:
- List stoc items (with pagination, filtering, searching)
- Create stock item
- Retrieve stock details
- Update stock
- Delete stock (soft delete)

**Filters Available**:
- product
- branch
- availability
- is_new_arrival
- is_top_pick
- supplier

---

### 2. **StockTransactionViewSet**
**Key Actions**:
- List transactions (read-only typically)
- Retrieve transaction details
- Create manual adjustments

---

### 3. **StockTransferViewSet**
**Key Actions**:
- Create transfer request
- List transfers
- Mark as delivered
- Cancel transfer

---

### 4. **StockAdjustmentViewSet**
**Key Actions**:
- Create adjustment
- Approve/reject adjustment
- List adjustment history

---

### 5. **VariationViewSet**
**Key Actions**:
- CRUD variations
- Upload variation images

---

## Critical Gaps & Issues

### 1. **Stock Level Synchronization** (CRITICAL - 30-40 hrs)
**Current State**:
- StockInventory.stock_level is denormalized integer field
- StockTransaction records transactions separately
- No automatic sync between them

**Problems**:
- ❌ Stock level can drift from reality
- ❌ No single source of truth
- ❌ Difficult to audit stock movements
- ❌ Manual reconciliation required

**Example**:
```python
# StockInventory says: stock_level = 100
# But StockTransactions show:
# INITIAL: +100 (total: 100)
# SALE: -50 (total: 50)
# PURCHASE: +30 (total: 80)
# System shows: 100 ❌ MISMATCH!
```

**Solution**:
- Make stock_level a computed property (sum of transactions)
- OR: Create transaction hook to auto-update stock_level
- Create scheduled reconciliation task
- Add stock_level_verified_at timestamp

---

### 2. **Missing FIFO/WEAC Valuation** (HIGH - 20-25 hrs)
**Current State**:
- No cost tracking per transaction
- No batch tracking
- manufacturing_cost field exists but not used

**Problems**:
- ❌ Can't calculate COGS accurately
- ❌ No cost-flow assumption implementation
- ❌ Can't track batch expiry for perishables
- ❌ Manufacturing cost not integrated with formulas

**Solution**:
- Add cost_per_unit to StockTransaction
- Implement FIFO batch tracking
- Create COGS calculation engine
- Link manufacturing batches to stock

---

### 3. **No Reorder Point Automation** (HIGH - 15-20 hrs)
**Current State**:
- reorder_level field exists
- No alerts or automatic orders
- availability field manually set

**Problems**:
- ❌ Can't trigger automatic PO creation
- ❌ Manual monitoring required
- ❌ Stockouts can occur
- ❌ availability field can be stale

**Solution**:
- Create reorder point alert system
- Implement auto-PO creation (with approval)
- Create demand forecasting
- Implement safety stock calculation

---

### 4. **StockTransfer Incomplete** (MEDIUM - 20-25 hrs)
**Current State**:
- StockTransfer model exists
- quantity_received field exists
- No reconciliation logic

**Problems**:
- ❌ In-transit items not deducted from source stock
- ❌ Transfer quantities not validated
- ❌ Can transfer more stock than available
- ❌ No partial receive handling

**Solution**:
- Create transaction hooks for transfer
- Validate available stock on transfer
- Implement partial receive logic
- Track stock "in-transit" separately

---

### 5. **No Stock Reconciliation** (HIGH - 15-20 hrs)
**Current State**:
- StockAdjustment model exists
- No scheduled reconciliation
- status field not tracked

**Problems**:
- ❌ Discrepancies not automatically detected
- ❌ No audit trail of approvals
- ❌ Physical counts manual

**Solution**:
- Create cycle count framework
- Implement variance analysis
- Create e-signature approval workflow
- Add barcode scanning support

---

### 6. **No Expiry/Batch Tracking** (MEDIUM - 15-20 hrs)
**Current State**:
- No expiry date field
- No batch number tracking
- Warranties exist but not linked to transactions

**Problems**:
- ❌ Can't mark expired stock
- ❌ No batch recall capability
- ❌ Expiry-driven discounting not possible

**Solution**:
- Add expiry_date to StockTransaction
- Add batch_number tracking
- Implement batch recall system
- Create expiry-based availability rules

---

### 7. **Stock Valuation Methods** (MEDIUM - 15-20 hrs)
**Current State**:
- No valuation method selection
- No inventory valuation report
- manufacturing_cost field exists but unused

**Problems**:
- ❌ Can't generate accurate balance sheet
- ❌ No FIFO/LIFO/Weighted Average support
- ❌ Can't analyze profitability per item

**Solution**:
- Implement FIFO/LIFO/Weighted Average engines
- Create inventory valuation report
- Link to manufacturing costs
- Create variance analysis

---

### 8. **No Multi-Location Support** (MEDIUM - 15-20 hrs)
**Current State**:
- branch field exists
- No multi-location queries optimized
- Transfer system incomplete

**Problems**:
- ❌ Can accidentally oversell across locations
- ❌ Transfer not integrated with stock movements
- ❌ Reporting across locations slow

**Solution**:
- Create location-aware stock rules
- Implement consolidated stock view
- Complete transfer integration
- Optimize multi-location queries

---

### 9. **Service Type Validation** (LOW - 5 hrs)
**Current State**:
- Prevents service products from having stock (in save method)
- Good practice but needs testing

**Enhancement**:
- Add model-level constraint validation
- Test edge cases
- Document why services can't have stock

---

### 10. **Test Coverage** (CRITICAL - 60-80 hrs)
**Current State**:
- Minimal tests exist (~25% coverage)

**Tests Needed**:
- Stock creation and validation (10 hrs)
- Transaction logging (15 hrs)
- Stock level calculation (15 hrs)
- Reorder logic and alerts (10 hrs)
- Transfer workflow (15 hrs)
- Adjustment and reconciliation (10 hrs)
- Multi-location scenarios (10 hrs)

---

## Performance Issues

### 1. **N+1 Query Problems**
```python
# Bad: Will query DB for each stock item's branch
for stock in StockInventory.objects.all():
    print(stock.branch.name)

# Good: Should be
StockInventory.objects.select_related('branch', 'product')
```

### 2. **Missing Indexes**
- Missing: (branch, availability)
- Missing: (product, branch) - for location stock
- Missing: (is_new_arrival, created_at)

### 3. **Slow Stock Calculation**
- Computing stock_level from transactions each time
- Need denormalized cache with invalidation

---

## Data Integrity Issues

### 1. **Constraint Violations**
- Stock_level can be negative (should be >= 0)
- No unique constraint on (product, branch, variation)
- Can create duplicate stock for same product/branch

### 2. **Foreign Key Issues**
- branch can be null (should be required)
- product deletion orphans stock entries
- supplier can be deleted leaving dangling reference

### 3. **Transaction Consistency**
- Creating StockTransaction doesn't create StockInventory
- Sale not reversed if customer refund rejected
- Manufacturing production not validated

---

## Database Relationships Map

```
StockInventory
├─ product (ForeignKey to Products)
├─ variation (ForeignKey to Variations)
│  └─ images (VariationImages)
├─ warranty (ForeignKey to Warranties)
├─ discount (ForeignKey to Discounts)
├─ applicable_tax (ForeignKey to Tax)
├─ unit (ForeignKey to Unit)
├─ branch (ForeignKey to Branch)
├─ supplier (ForeignKey to Contact)
└─ StockTransaction (Reverse relation)
   ├─ reference_number (links to source doc)
   ├─ cost_per_unit
   └─ branch (ForeignKey)

StockTransfer
├─ source_branch (ForeignKey)
├─ destination_branch (ForeignKey)
├─ transferred_by (ForeignKey to User)
├─ received_by (ForeignKey to User)
└─ StockTransferItem (Reverse)
   ├─ stock_item (ForeignKey)
   └─ quantity_received tracking

StockAdjustment
├─ stock_item (ForeignKey)
├─ adjusted_by (ForeignKey to User)
└─ status workflow: pending → approved/rejected
```

---

## Recommended Implementation Roadmap

### Phase 1 (Weeks 1-3): Critical Fixes
1. **Stock Level Synchronization** (30 hrs)
   - Make stock_level computed property
   - Add transaction hooks
   - Create reconciliation task

2. **Stock Transfer Integration** (20 hrs)
   - Auto-create transactions on transfer
   - Validate available stock
   - Implement partial receive

3. **Test Expansion** (30 hrs)
   - Stock CRUD operations
   - Transaction logging
   - Transfer workflows

### Phase 2 (Weeks 4-6): High Priority
1. **Reorder Point Automation** (15 hrs)
   - Alert system
   - Auto-PO creation
   - Safety stock logic

2. **Cost Tracking & Valuation** (20 hrs)
   - FIFO batch tracking
   - COGS calculation
   - Valuation methods

3. **Stock Reconciliation Framework** (15 hrs)
   - Cycle count support
   - Variance analysis
   - Approval workflow

### Phase 3 (Weeks 7-10): Medium Priority
1. **Expiry/Batch Tracking** (15 hrs)
2. **Multi-location Optimization** (15 hrs)
3. **Inventory Reporting** (20 hrs)

### Phase 4+: Long-term
1. Serial number tracking
2. Barcode/QR code integration
3. Advanced demand forecasting
4. Supplier integration

---

## Testing Strategy

### Unit Tests
- Stock creation and default values
- Price calculation and profit margins
- Service item validation
- Unit conversions
- Variation handling

### Integration Tests
- Complete stock flow (purchase → sale → return)
- Multi-location transfers
- Stock adjustment and reconciliation
- Manufacturing to stock flow
- ProcurementOrder to StockInventory

### API Tests
- All CRUD endpoints
- Filter and search functionality
- Stock level reporting
- Transaction history
- Transfer workflows

---

## Conclusion

**Inventory module provides basic stock tracking** with:
- ✓ Product stock management
- ✓ Transaction logging
- ✓ Multi-location support
- ✓ Warranty/discount integration

**But critical issues need fixing**:
- ❌ Stock level synchronization broken
- ❌ No FIFO/cost tracking
- ❌ Reorder automation missing
- ❌ Transfer logic incomplete
- ❌ Low test coverage
- ❌ No batch/expiry tracking

**Estimated Effort**: 250-350 hours over 3-4 months

