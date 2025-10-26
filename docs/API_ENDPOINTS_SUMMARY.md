# Report API Endpoints Summary

Complete reference for all production-ready report endpoints for UI consumption.

## Overview

All endpoints support:
- ✅ Multiple export formats (CSV, PDF, Excel)
- ✅ Business/branch filtering
- ✅ Date range filtering
- ✅ Professional company branding
- ✅ Comprehensive error handling
- ✅ JSON response with tabular data

---

## Payroll Reports (`/api/hrm/payroll/reports/`)

### 1. P9 Tax Report
**Endpoint**: `GET /api/hrm/payroll/reports/p9-tax/`

**Parameters**:
- `start_date`: Period start (YYYY-MM-DD, optional)
- `end_date`: Period end (YYYY-MM-DD, optional)
- `year`: Year (YYYY, optional, used if dates not provided)
- `month`: Month (MM, optional)
- `employee_ids`: Comma-separated employee IDs (optional)
- `department_ids`: Comma-separated department IDs (optional)
- `branch_id`: Branch ID (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "P9 Tax Deduction Card",
  "data": [...],
  "totals": {
    "total_employees": 50,
    "total_tax": 500000,
    "total_reliefs": 100000
  },
  "columns": [...]
}
```

### 2. P10A Employer Return (Multi-format)
**Endpoint**: `GET /api/hrm/payroll/reports/p10a-employer-return/`

**Parameters**:
- `year`: Tax year (YYYY, required)
- `employee_ids`: Comma-separated employee IDs (optional)
- `department_ids`: Comma-separated department IDs (optional)
- `branch_id`: Branch ID (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "P10A",
  "tabs": {
    "B_Employee_Details": {
      "data": [...],
      "columns": [...],
      "title": "Tab B: Employee Details"
    },
    "D_FBT_Details": {...},
    "M_Housing_Levy_Details": {...},
    "C_Lump_Sum_Payments": {...}
  },
  "totals": {
    "total_employees": 50,
    "total_gross_pay": 5000000
  },
  "kra_compliance": {
    "format_version": "07/2025",
    "tabs_required": ["B"],
    "tabs_conditional": ["C", "D", "M"]
  }
}
```

### 3. Statutory Deductions Report
**Endpoint**: `GET /api/hrm/payroll/reports/statutory-deductions/`

**Parameters**:
- `deduction_type`: `nssf`, `nhif`, `shif`, `nita` (optional)
- `payment_period`: YYYY-MM-DD (optional)
- `year`: YYYY (optional)
- `month`: MM (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Statutory Deductions",
  "deduction_type": "nssf",
  "data": [...],
  "totals": {
    "total_deductions": 250000,
    "total_employees": 50
  }
}
```

### 4. Bank Net Pay Report
**Endpoint**: `GET /api/hrm/payroll/reports/bank-net-pay/`

**Parameters**:
- `payment_period`: YYYY-MM-DD (optional)
- `year`: YYYY (optional)
- `month`: MM (optional)
- `branch_id`: Branch ID (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Bank Net Pay",
  "data": [...],
  "totals": {
    "total_net_pay": 4000000,
    "total_employees": 50,
    "bank_branches": 3
  }
}
```

### 5. Muster Roll Report
**Endpoint**: `GET /api/hrm/payroll/reports/muster-roll/`

**Parameters**:
- `payment_period`: YYYY-MM-DD (optional)
- `year`: YYYY (optional)
- `month`: MM (optional)
- `department_ids`: Comma-separated department IDs (optional)
- `dynamic_columns`: `true`/`false` (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Muster Roll",
  "data": [...],
  "dynamic_columns": [...],
  "totals": {
    "total_gross": 5000000,
    "total_deductions": 1000000,
    "total_net": 4000000
  }
}
```

### 6. Withholding Tax Report
**Endpoint**: `GET /api/hrm/payroll/reports/withholding-tax/`

**Parameters**:
- `payment_period`: YYYY-MM-DD (optional)
- `year`: YYYY (optional)
- `month`: MM (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Withholding Tax",
  "data": [...],
  "totals": {
    "total_withholding": 150000,
    "total_transactions": 100
  }
}
```

### 7. Variance Report
**Endpoint**: `GET /api/hrm/payroll/reports/variance/`

**Parameters**:
- `current_period`: YYYY-MM (required)
- `previous_period`: YYYY-MM (optional)
- `department_ids`: Comma-separated department IDs (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Variance Analysis",
  "data": [...],
  "variance_metrics": {
    "total_variance": 50000,
    "variance_percentage": 2.5
  }
}
```

---

## Finance Reports (`/api/finance/reports/`)

### 1. Profit & Loss Statement
**Endpoint**: `GET /api/finance/reports/profit-loss/`

**Parameters**:
- `start_date`: Period start (YYYY-MM-DD, default: 30 days ago)
- `end_date`: Period end (YYYY-MM-DD, default: today)
- `business_id`: Business ID (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "P&L Statement",
  "data": [
    {
      "line_item": "100 - Revenue",
      "description": "Total Sales Revenue",
      "current_period": 5000000,
      "previous_period": 4800000,
      "variance_amount": 200000,
      "variance_percent": 4.17
    }
  ],
  "totals": {
    "current_revenue": 5000000,
    "previous_revenue": 4800000,
    "current_net_income": 500000,
    "previous_net_income": 400000
  },
  "metrics": {
    "gross_margin_current": 45.0,
    "gross_margin_previous": 42.0,
    "net_margin_current": 10.0,
    "net_margin_previous": 8.33
  }
}
```

### 2. Balance Sheet
**Endpoint**: `GET /api/finance/reports/balance-sheet/`

**Parameters**:
- `as_of_date`: Balance sheet date (YYYY-MM-DD, default: today)
- `comparison_date`: Comparison date (YYYY-MM-DD, default: 365 days prior)
- `business_id`: Business ID (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Balance Sheet",
  "data": [...],
  "totals": {
    "total_assets": 10000000,
    "total_liabilities": 3000000,
    "total_equity": 7000000
  },
  "validation": {
    "equation_balanced": true,
    "assets_equal_liab_equity": true
  }
}
```

### 3. Cash Flow Statement
**Endpoint**: `GET /api/finance/reports/cash-flow/`

**Parameters**:
- `start_date`: Period start (YYYY-MM-DD, default: 30 days ago)
- `end_date`: Period end (YYYY-MM-DD, default: today)
- `business_id`: Business ID (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Cash Flow Statement",
  "data": [...],
  "totals": {
    "operating_net": 800000,
    "investing_net": -200000,
    "financing_net": 100000,
    "net_cash_change": 700000
  }
}
```

### 4. Financial Statements Suite
**Endpoint**: `GET /api/finance/reports/statements-suite/`

**Parameters**:
- `start_date`: Period start (YYYY-MM-DD, default: 30 days ago)
- `end_date`: Period end (YYYY-MM-DD, default: today)
- `business_id`: Business ID (optional)

**Returns**:
```json
{
  "p_and_l": {...},
  "balance_sheet": {...},
  "cash_flow": {...},
  "generated_at": "2025-10-23T10:30:00Z"
}
```

---

## E-commerce Reports (`/api/ecommerce/reports/`)

### 1. Sales Dashboard
**Endpoint**: `GET /api/ecommerce/reports/sales-dashboard/`

**Parameters**:
- `start_date`: Period start (YYYY-MM-DD, default: 30 days ago)
- `end_date`: Period end (YYYY-MM-DD, default: today)
- `period_type`: `daily`, `weekly`, `monthly` (default: daily)
- `business_id`: Business ID (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Sales Dashboard",
  "data": [
    {
      "period": "2025-10-01",
      "total_orders": 25,
      "total_sales": 500000,
      "average_order_value": 20000,
      "units_sold": 150,
      "order_growth": 15.5,
      "revenue_growth": 12.3
    }
  ],
  "summary": {
    "total_orders": 750,
    "total_sales": 15000000,
    "average_order_value": 20000,
    "total_units": 4500,
    "order_growth_percent": 12.5,
    "revenue_growth_percent": 10.3
  }
}
```

### 2. Product Performance
**Endpoint**: `GET /api/ecommerce/reports/product-performance/`

**Parameters**:
- `start_date`: Period start (YYYY-MM-DD, default: 30 days ago)
- `end_date`: Period end (YYYY-MM-DD, default: today)
- `top_n`: Top N products (default: 50)
- `business_id`: Business ID (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Product Performance",
  "data": [
    {
      "product_name": "Laptop Dell XPS",
      "sku": "DELL-XPS-001",
      "category": "Electronics",
      "units_sold": 45,
      "revenue": 2250000,
      "avg_selling_price": 50000,
      "profit_margin_percent": 25.5,
      "rank": 1
    }
  ],
  "summary": {
    "total_products": 150,
    "total_units_sold": 4500,
    "total_revenue": 15000000,
    "average_margin": 23.7
  }
}
```

### 3. Customer Analysis
**Endpoint**: `GET /api/ecommerce/reports/customer-analysis/`

**Parameters**:
- `start_date`: Period start (YYYY-MM-DD, default: 30 days ago)
- `end_date`: Period end (YYYY-MM-DD, default: today)
- `min_orders`: Minimum orders (default: 1)
- `business_id`: Business ID (optional)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Customer Analysis",
  "data": [
    {
      "customer_name": "John Doe",
      "email": "john@example.com",
      "total_orders": 15,
      "lifetime_value": 750000,
      "average_order_value": 50000,
      "first_order_date": "2025-01-15",
      "last_order_date": "2025-10-20",
      "segment": "VIP"
    }
  ],
  "segments": {
    "vip": 50,
    "loyal": 150,
    "regular": 300,
    "new": 500
  },
  "summary": {
    "total_customers": 1000,
    "total_lifetime_value": 50000000,
    "average_lifetime_value": 50000
  }
}
```

### 4. Inventory Management
**Endpoint**: `GET /api/ecommerce/reports/inventory-management/`

**Parameters**:
- `business_id`: Business ID (optional)
- `include_low_stock`: Include low stock items (default: true)
- `export`: Export format - `csv`, `pdf`, `xlsx` (optional)

**Returns**:
```json
{
  "report_type": "Inventory Management",
  "data": [
    {
      "product_name": "Laptop Dell XPS",
      "sku": "DELL-XPS-001",
      "category": "Electronics",
      "current_stock": 25,
      "reorder_level": 10,
      "status": "Adequate",
      "stock_value": 1250000,
      "turnover_rate": "N/A"
    }
  ],
  "summary": {
    "total_items": 500,
    "total_stock_value": 25000000,
    "low_stock_items": 45,
    "adequate_stock": 350,
    "monitor_stock": 105
  }
}
```

### 5. E-commerce Reports Suite
**Endpoint**: `GET /api/ecommerce/reports/suite/`

**Parameters**:
- `start_date`: Period start (YYYY-MM-DD, default: 30 days ago)
- `end_date`: Period end (YYYY-MM-DD, default: today)
- `business_id`: Business ID (optional)

**Returns**:
```json
{
  "sales_dashboard": {...},
  "product_performance": {...},
  "customer_analysis": {...},
  "inventory": {...},
  "generated_at": "2025-10-23T10:30:00Z"
}
```

---

## Export Formats

All endpoints support export parameter `export` with values:

### CSV Export
- **Format**: `export=csv`
- **Content-Type**: `text/csv`
- **Usage**: Import into Excel, Google Sheets, etc.
- **Features**: Proper numeric formatting

### PDF Export
- **Format**: `export=pdf`
- **Content-Type**: `application/pdf`
- **Usage**: Professional documents, printing
- **Features**: Company branding, headers, footers

### Excel Export
- **Format**: `export=xlsx`
- **Content-Type**: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **Usage**: Advanced analysis in Excel
- **Features**: Professional styling, colors, auto-width columns, number formatting

---

## Common Query Parameters

### Date Parameters
- Format: `YYYY-MM-DD` (ISO 8601)
- Example: `?start_date=2025-01-01&end_date=2025-10-31`

### Filtering
- `business_id`: Filter by business
- `branch_id`: Filter by branch
- `department_ids`: Comma-separated department IDs

### Export
- `export`: `csv`, `pdf`, or `xlsx`
- Default: JSON response

---

## Error Responses

All endpoints return appropriate HTTP status codes:

### Success
- `200 OK`: Report generated successfully

### Client Errors
- `400 Bad Request`: Invalid parameters (e.g., invalid date format, start_date > end_date)
- `401 Unauthorized`: Authentication required
- `403 Forbidden`: Permission denied

### Server Errors
- `500 Internal Server Error`: Server error during report generation

**Error Response Format**:
```json
{
  "error": "Error description",
  "report_type": "Report Type"
}
```

---

## Authentication

All endpoints require authentication:
- Header: `Authorization: Bearer <token>`
- Method: JWT or session-based (depending on implementation)

---

## Response Structure

All report responses follow consistent structure:

```json
{
  "report_type": "String",
  "data": [
    {...row data...},
    {...row data...}
  ],
  "columns": [
    {
      "field": "column_key",
      "header": "Display Header"
    }
  ],
  "title": "Report Title",
  "totals": {...},
  "summary": {...},
  "row_count": 100,
  "generated_at": "ISO8601 timestamp"
}
```

---

## Performance Considerations

- ✅ Database aggregation at query level (no N+1 queries)
- ✅ Efficient filtering and date ranges
- ✅ Polars-based data processing for large datasets
- ✅ Caching recommendations (set Cache-Control headers)
- ✅ Pagination support (for future enhancement)

---

## UI Integration Examples

### JavaScript Fetch
```javascript
// Get sales dashboard
const response = await fetch(
  '/api/ecommerce/reports/sales-dashboard/?start_date=2025-01-01&end_date=2025-10-31',
  {
    headers: {'Authorization': 'Bearer ' + token}
  }
);
const report = await response.json();

// Export as Excel
const exportUrl = '/api/ecommerce/reports/sales-dashboard/?start_date=2025-01-01&end_date=2025-10-31&export=xlsx';
window.location.href = exportUrl;
```

### React Component Integration
```javascript
async function fetchReport(reportType, params) {
  const queryString = new URLSearchParams(params).toString();
  const response = await fetch(`/api/${reportType}/?${queryString}`);
  if (!response.ok) throw new Error('Report failed');
  return await response.json();
}
```

---

## Versioning

Current API Version: **v1**

All endpoints are production-ready and stable.

---

## Last Updated

October 23, 2025

**Status**: ✅ All 19 report endpoints production-ready for UI consumption
