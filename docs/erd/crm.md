# ERP Service - CRM Module Entity Relationship Diagram

The CRM module manages customer relationships, leads, opportunities, sales pipeline, and marketing campaigns.

> **Conventions**
> - UUID primary keys (Django uses auto-incrementing integers by default, but can be configured for UUIDs).
> - `tenant_id` (via `business_id` and `branch_id`) on all operational tables for multi-tenant isolation.
> - Timestamps are `TIMESTAMPTZ` with timezone awareness.
> - Monetary values use `DECIMAL(14,2)` or `DECIMAL(15,2)` with decimal precision.
> - All tables include `created_at` and `updated_at` timestamps.
> - Soft deletes via `is_deleted` boolean flag where applicable.

---

## Contacts & Customer Groups

### customer_groups

**Purpose**: Customer segmentation and group-based discount management.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Group identifier |
| `group_name` | VARCHAR(100) | | Group name |
| `dicount_calculation` | VARCHAR(100) | CHECK | Percentage or Fixed |
| `amount` | DECIMAL(14,2) | DEFAULT 0.00 | Discount amount |

**Indexes**:
- `idx_customer_group_name` ON `group_name`
- `idx_customer_group_discount` ON `dicount_calculation`

### contacts

**Purpose**: Customer, supplier, and partner contact management.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Contact identifier |
| `contact_id` | VARCHAR(100) | NOT NULL | Unique contact identifier |
| `contact_type` | VARCHAR(100) | CHECK | Suppliers, Customers, Customers & Suppliers |
| `user_id` | INTEGER | FK → auth_users(id) | User reference (from auth-service) |
| `business_id` | INTEGER | FK → businesses(id) | Business/tenant reference |
| `branch_id` | INTEGER | FK → branches(id) | Branch reference |
| `designation` | VARCHAR(100) | | Mr/Mrs/Ms |
| `customer_group_id` | INTEGER | FK → customer_groups(id) | Customer group reference |
| `account_type` | VARCHAR(100) | CHECK | Individual or Business |
| `tax_number` | VARCHAR(100) | | Tax number (for businesses) |
| `business_name` | VARCHAR(100) | | Business name (if business) |
| `business_address` | VARCHAR(100) | | Business address |
| `alternative_contact` | VARCHAR(15) | | Alternative phone |
| `phone` | VARCHAR(15) | | Primary phone |
| `credit_limit` | DECIMAL(14,2) | | Credit limit |
| `added_on` | DATE | DEFAULT NOW() | Date added |
| `is_deleted` | BOOLEAN | DEFAULT false | Soft delete flag |
| `created_by_id` | INTEGER | FK → auth_users(id) | Creator user reference |

**Indexes**:
- `idx_contact_id` ON `contact_id`
- `idx_contact_type` ON `contact_type`
- `idx_contact_user` ON `user_id`
- `idx_contact_business` ON `business_id`
- `idx_contact_branch` ON `branch_id`
- `idx_contact_customer_group` ON `customer_group_id`
- `idx_contact_account_type` ON `account_type`
- `idx_contact_phone` ON `phone`
- `idx_contact_deleted` ON `is_deleted`
- `idx_contact_added_on` ON `added_on`

**Relations**:
- `user_id` → `auth_users(id)` (references auth-service)
- `business_id` → `businesses(id)` (tenant reference)
- `branch_id` → `branches(id)` (outlet reference)
- `customer_group_id` → `customer_groups(id)`
- `created_by_id` → `auth_users(id)` (references auth-service)

### contact_accounts

**Purpose**: Contact financial account balances and tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Account identifier |
| `contact_id` | INTEGER | FK → contacts(id) | Contact reference |
| `account_balance` | DECIMAL(14,2) | DEFAULT 0.00 | Opening balance |
| `advance_balance` | DECIMAL(14,2) | DEFAULT 0.00 | Advance balance |
| `total_sale_due` | DECIMAL(14,2) | DEFAULT 0.00 | Total sale due |
| `total_sale_return_due` | DECIMAL(14,2) | DEFAULT 0.00 | Total sale return due |

**Indexes**:
- `idx_contact_account_contact` ON `contact_id`

**Relations**:
- `contact_id` → `contacts(id)`

**Note**: Financial transactions are managed by treasury-app. This table tracks account balances for reference only.

---

## Leads Management

### crm_leads

**Purpose**: Sales lead capture, qualification, and conversion tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Lead identifier |
| `contact_id` | INTEGER | FK → contacts(id) | Contact reference |
| `source` | VARCHAR(100) | | Lead source |
| `status` | VARCHAR(20) | CHECK | new, contacted, qualified, won, lost |
| `value` | DECIMAL(15,2) | DEFAULT 0.00 | Lead value |
| `owner_id` | INTEGER | FK → auth_users(id) | Lead owner (references auth-service) |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_lead_status` ON `status`
- `idx_lead_contact` ON `contact_id`
- `idx_lead_source` ON `source`
- `idx_lead_owner` ON `owner_id`
- `idx_lead_created_at` ON `created_at`
- `idx_lead_updated_at` ON `updated_at`

**Relations**:
- `contact_id` → `contacts(id)`
- `owner_id` → `auth_users(id)` (references auth-service)

---

## Sales Pipeline

### crm_pipeline_stages

**Purpose**: Sales pipeline stage definitions.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Stage identifier |
| `name` | VARCHAR(100) | NOT NULL | Stage name |
| `order` | INTEGER | DEFAULT 0 | Stage order |
| `is_won` | BOOLEAN | DEFAULT false | Won stage flag |
| `is_lost` | BOOLEAN | DEFAULT false | Lost stage flag |

**Indexes**:
- `idx_pipeline_stage_name` ON `name`
- `idx_pipeline_stage_order` ON `order`
- `idx_pipeline_stage_is_won` ON `is_won`
- `idx_pipeline_stage_is_lost` ON `is_lost`

### crm_deals

**Purpose**: Sales opportunities and deals in the pipeline.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Deal identifier |
| `title` | VARCHAR(255) | NOT NULL | Deal title |
| `contact_id` | INTEGER | FK → contacts(id) | Contact reference |
| `lead_id` | INTEGER | FK → crm_leads(id) | Lead reference (optional) |
| `stage_id` | INTEGER | FK → crm_pipeline_stages(id) | Pipeline stage |
| `amount` | DECIMAL(15,2) | DEFAULT 0.00 | Deal amount |
| `close_date` | DATE | | Expected close date |
| `owner_id` | INTEGER | FK → auth_users(id) | Deal owner (references auth-service) |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_deal_stage` ON `stage_id`
- `idx_deal_contact` ON `contact_id`
- `idx_deal_lead` ON `lead_id`
- `idx_deal_owner` ON `owner_id`
- `idx_deal_close_date` ON `close_date`
- `idx_deal_created_at` ON `created_at`
- `idx_deal_updated_at` ON `updated_at`

**Relations**:
- `contact_id` → `contacts(id)`
- `lead_id` → `crm_leads(id)`
- `stage_id` → `crm_pipeline_stages(id)`
- `owner_id` → `auth_users(id)` (references auth-service)

**Integration Points**:
- When deal reaches "won" stage → Publish `erp.opportunity.won` event → treasury-app creates invoice

---

## Marketing Campaigns

### crm_campaigns

**Purpose**: Marketing campaign management and tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Campaign identifier |
| `name` | VARCHAR(255) | NOT NULL | Campaign name |
| `campaign_type` | VARCHAR(50) | CHECK | banner, email, social, sms, promotional, seasonal, product_launch, loyalty |
| `status` | VARCHAR(20) | CHECK | draft, active, paused, completed, cancelled |
| `priority` | INTEGER | CHECK | 1-5 (Highest to Lowest) |
| `title` | VARCHAR(200) | | Campaign title |
| `description` | TEXT | | Campaign description |
| `image` | VARCHAR(255) | | Image file path |
| `badge` | VARCHAR(200) | DEFAULT "New" | Badge text |
| `seller_id` | INTEGER | FK → contacts(id) | Seller contact (for banner campaigns) |
| `branch_id` | INTEGER | FK → branches(id) | Branch reference |
| `start_date` | TIMESTAMPTZ | | Campaign start date |
| `end_date` | TIMESTAMPTZ | | Campaign end date |
| `is_active` | BOOLEAN | DEFAULT true | Active flag |
| `is_default` | BOOLEAN | DEFAULT false | Default campaign flag |
| `impressions` | INTEGER | DEFAULT 0 | Impression count |
| `clicks` | INTEGER | DEFAULT 0 | Click count |
| `conversions` | INTEGER | DEFAULT 0 | Conversion count |
| `revenue_generated` | DECIMAL(15,2) | DEFAULT 0.00 | Revenue generated |
| `budget` | DECIMAL(15,2) | | Campaign budget |
| `max_impressions` | INTEGER | | Maximum impressions |
| `max_clicks` | INTEGER | | Maximum clicks |
| `landing_page_url` | VARCHAR(255) | | Landing page URL |
| `cta_text` | VARCHAR(100) | DEFAULT "Learn More" | Call-to-action text |
| `created_by_id` | INTEGER | FK → auth_users(id) | Creator (references auth-service) |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_campaign_type` ON `campaign_type`
- `idx_campaign_status` ON `status`
- `idx_campaign_start_date` ON `start_date`
- `idx_campaign_end_date` ON `end_date`
- `idx_campaign_is_active` ON `is_active`

**Relations**:
- `seller_id` → `contacts(id)` (where contact_type = 'Suppliers')
- `branch_id` → `branches(id)`
- `created_by_id` → `auth_users(id)` (references auth-service)

**Many-to-Many Relations**:
- `target_audience` → `contacts` (via junction table)
- `target_branches` → `branches` (via junction table)
- `featured_products` → `stock_inventory` (via junction table)
- `stock_items` → `stock_inventory` (via junction table)

### crm_campaign_performance

**Purpose**: Campaign performance metrics and analytics.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Performance record identifier |
| `campaign_id` | INTEGER | FK → crm_campaigns(id) | Campaign reference |
| `date` | DATE | | Performance date |
| `impressions` | INTEGER | DEFAULT 0 | Daily impressions |
| `clicks` | INTEGER | DEFAULT 0 | Daily clicks |
| `conversions` | INTEGER | DEFAULT 0 | Daily conversions |
| `revenue` | DECIMAL(15,2) | DEFAULT 0.00 | Daily revenue |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

**Indexes**:
- `idx_campaign_performance_campaign` ON `campaign_id`
- `idx_campaign_performance_date` ON `date`

**Relations**:
- `campaign_id` → `crm_campaigns(id)`

---

## Integration Points

### External Service References

**Auth Service**:
- `contacts.user_id` → `auth_users(id)` (user identity)
- `crm_leads.owner_id` → `auth_users(id)` (lead owner)
- `crm_deals.owner_id` → `auth_users(id)` (deal owner)
- `crm_campaigns.created_by_id` → `auth_users(id)` (campaign creator)

**Treasury Service**:
- When `crm_deals.status` = "won" → Publish `erp.opportunity.won` event → treasury-app creates invoice
- `contact_accounts` balances are reference only (actual transactions in treasury-app)

**Notifications Service**:
- Campaign emails → Publish `erp.campaign.sent` event
- Lead notifications → Publish `erp.lead.qualified` event

**Inventory Service**:
- `crm_campaigns.featured_products` → References `stock_inventory` (product catalog)

---

## Views & Functions

### Recommended Views

**v_crm_contact_summary**:
- Contact details with account balances
- Total leads, deals, and revenue

**v_crm_pipeline_summary**:
- Deal counts by stage
- Total pipeline value
- Conversion rates

**v_crm_campaign_performance**:
- Campaign metrics aggregated by date
- ROI calculations

---

## Maintenance Notes

- Maintain this document alongside Django model changes.
- After changing Django models, run migrations and refresh the ERD.
- Financial transactions are managed by treasury-app - do not duplicate financial logic.
- User management is handled by auth-service - reference user IDs only.

