# MoneyField Serializer Guide

## Overview

The `MoneyField` is a custom Django REST Framework serializer field that enhances monetary values with currency information. Instead of returning just a number, it returns an object with the amount, currency code, and formatted string.

## Benefits

1. **Frontend gets currency info automatically** - No need to guess the currency
2. **Automatic formatting** - Backend provides formatted string (e.g., "KSh 1,000.00")
3. **Backward compatible** - Can use `simple_mode=True` for legacy endpoints
4. **Consistent across all endpoints** - Same money representation everywhere

## Response Format

### Enhanced Mode (Default)
```json
{
  "total": {
    "amount": 1000.00,
    "currency": "KES",
    "formatted": "KSh 1,000.00"
  }
}
```

### Simple Mode (Legacy Compatible)
```json
{
  "total": 1000.00
}
```

## Usage Examples

### Example 1: Static Currency

When all amounts are in the same currency (e.g., company base currency):

```python
from rest_framework import serializers
from core.serializer_fields import MoneyField

class InvoiceSerializer(serializers.ModelSerializer):
    total = MoneyField(max_digits=15, decimal_places=2, source_currency='KES')
    subtotal = MoneyField(max_digits=15, decimal_places=2, source_currency='KES')
    tax_amount = MoneyField(max_digits=15, decimal_places=2, source_currency='KES')

    class Meta:
        model = Invoice
        fields = ['id', 'invoice_number', 'total', 'subtotal', 'tax_amount']
```

**Response:**
```json
{
  "id": 1,
  "invoice_number": "INV-001",
  "total": {
    "amount": "1500.00",
    "currency": "KES",
    "formatted": "KSh 1,500.00"
  },
  "subtotal": {
    "amount": "1200.00",
    "currency": "KES",
    "formatted": "KSh 1,200.00"
  },
  "tax_amount": {
    "amount": "300.00",
    "currency": "KES",
    "formatted": "KSh 300.00"
  }
}
```

### Example 2: Dynamic Currency from Model Field

When each record can have a different currency:

```python
from rest_framework import serializers
from core.serializer_fields import MoneyField

class OrderSerializer(serializers.ModelSerializer):
    # Model has 'currency' field - will be used automatically
    total = MoneyField(max_digits=15, decimal_places=2)

    # OR explicitly specify the currency field name
    subtotal = MoneyField(max_digits=15, decimal_places=2, currency_field='currency')

    class Meta:
        model = Order
        fields = ['id', 'order_number', 'currency', 'total', 'subtotal']
```

**Model:**
```python
class Order(models.Model):
    order_number = models.CharField(max_length=100)
    currency = models.CharField(max_length=3, default='KES')  # This is auto-detected
    total = models.DecimalField(max_digits=15, decimal_places=2)
    subtotal = models.DecimalField(max_digits=15, decimal_places=2)
```

**Response:**
```json
{
  "id": 1,
  "order_number": "ORD-001",
  "currency": "USD",
  "total": {
    "amount": "500.00",
    "currency": "USD",
    "formatted": "$500.00"
  },
  "subtotal": {
    "amount": "450.00",
    "currency": "USD",
    "formatted": "$450.00"
  }
}
```

### Example 3: Mixed Approach (Some Static, Some Dynamic)

```python
from rest_framework import serializers
from core.serializer_fields import MoneyField

class PaymentSerializer(serializers.ModelSerializer):
    # Static KES for local amounts
    fee = MoneyField(max_digits=10, decimal_places=2, source_currency='KES')

    # Dynamic currency for payment amount
    amount = MoneyField(max_digits=15, decimal_places=2, currency_field='currency')

    class Meta:
        model = Payment
        fields = ['id', 'amount', 'currency', 'fee', 'status']
```

### Example 4: Dashboard Aggregates

For dashboard endpoints that return aggregated financial data:

```python
from rest_framework.decorators import api_view
from rest_framework.response import Response
from core.serializer_fields import format_money

@api_view(['GET'])
def finance_dashboard(request):
    period = request.query_params.get('period', 'month')

    # Get aggregated data
    total_revenue = get_total_revenue(period)  # Returns Decimal
    total_expenses = get_total_expenses(period)  # Returns Decimal
    net_profit = total_revenue - total_expenses

    # Format all amounts with currency info
    data = {
        'total_revenue': format_money(total_revenue, 'KES'),
        'total_expenses': format_money(total_expenses, 'KES'),
        'net_profit': format_money(net_profit, 'KES'),
        'period': period
    }

    return Response(data)
```

**Response:**
```json
{
  "total_revenue": {
    "amount": 150000.00,
    "currency": "KES",
    "formatted": "KSh 150,000.00"
  },
  "total_expenses": {
    "amount": 75000.00,
    "currency": "KES",
    "formatted": "KSh 75,000.00"
  },
  "net_profit": {
    "amount": 75000.00,
    "currency": "KES",
    "formatted": "KSh 75,000.00"
  },
  "period": "month"
}
```

### Example 5: Backward Compatible Migration

When you need to maintain backward compatibility:

```python
from rest_framework import serializers
from core.serializer_fields import MoneyField

class InvoiceSerializer(serializers.ModelSerializer):
    # New enhanced field
    total_enhanced = MoneyField(
        max_digits=15,
        decimal_places=2,
        source='total',
        source_currency='KES'
    )

    # Old simple field (for legacy clients)
    total = MoneyField(
        max_digits=15,
        decimal_places=2,
        simple_mode=True,  # Returns just the number
        source_currency='KES'
    )

    class Meta:
        model = Invoice
        fields = ['id', 'total', 'total_enhanced']
```

**Response:**
```json
{
  "id": 1,
  "total": 1500.00,
  "total_enhanced": {
    "amount": "1500.00",
    "currency": "KES",
    "formatted": "KSh 1,500.00"
  }
}
```

## Frontend Usage

### With Enhanced Format

```javascript
// Fetch data
const invoice = await api.get('/invoices/1/');

// Access amount
const amount = invoice.total.amount;  // 1500.00

// Access currency
const currency = invoice.total.currency;  // "KES"

// Display formatted (no need to format on frontend!)
document.getElementById('total').textContent = invoice.total.formatted;  // "KSh 1,500.00"

// Or use for currency conversion
const { convertAndFormat } = useGlobalCurrency();
const converted = convertAndFormat(invoice.total.amount, invoice.total.currency);
```

### Automatic Currency Handling

With the enhanced format, the frontend's `formatCurrencySync` will automatically know the source currency:

```javascript
import { useGlobalCurrency } from '@/composables/useGlobalCurrency';

const { formatCurrencySync } = useGlobalCurrency();

// Backend returns: { amount: 1000, currency: "KES", formatted: "KSh 1,000.00" }
const invoice = await api.get('/invoices/1/');

// Now formatCurrencySync knows it's KES and will convert if needed
const formattedTotal = formatCurrencySync(
    invoice.total.amount,
    invoice.total.currency  // Source currency from backend!
);
```

## Migration Strategy

### Phase 1: Add MoneyField to New Endpoints
- Use MoneyField for all new API endpoints
- Set `simple_mode=False` (default) for enhanced format

### Phase 2: Gradual Migration of Existing Endpoints
- Add new enhanced fields alongside existing fields
- Update frontend to use new fields
- Keep old fields for backward compatibility

### Phase 3: Update Frontend
- Update components to read currency from backend
- Remove hardcoded currency assumptions
- Use `formatCurrencySync(amount, response.currency)` pattern

### Phase 4: Deprecate Simple Fields
- Remove old simple numeric fields
- All endpoints use enhanced format
- Frontend expects currency info with all amounts

## Helper Function: format_money()

For non-serializer contexts (views, background jobs, etc.):

```python
from core.serializer_fields import format_money

# In a view
total = calculate_invoice_total(invoice)
formatted = format_money(total, 'KES')

return Response({
    'invoice_id': invoice.id,
    'total': formatted  # { amount, currency, formatted }
})

# In a background job
payment_amount = process_payment(payment)
notification_data = {
    'payment': format_money(payment_amount, payment.currency),
    'status': 'completed'
}
send_notification(notification_data)
```

## Supported Currencies

The MoneyField supports 15 currencies with proper symbols and decimal places:

| Code | Name | Symbol | Decimals |
|------|------|--------|----------|
| KES | Kenya Shilling | KSh | 2 |
| USD | US Dollar | $ | 2 |
| EUR | Euro | € | 2 |
| GBP | British Pound | £ | 2 |
| UGX | Uganda Shilling | USh | 0 |
| TZS | Tanzania Shilling | TSh | 0 |
| ZAR | South African Rand | R | 2 |
| NGN | Nigerian Naira | ₦ | 2 |
| GHS | Ghanaian Cedi | GH₵ | 2 |
| RWF | Rwandan Franc | FRw | 0 |
| ETB | Ethiopian Birr | Br | 2 |
| AED | UAE Dirham | د.إ | 2 |
| INR | Indian Rupee | ₹ | 2 |
| CNY | Chinese Yuan | ¥ | 2 |
| JPY | Japanese Yen | ¥ | 0 |

## Best Practices

1. **Always specify source_currency or currency_field** - Don't rely on fallback
2. **Use enhanced format for new endpoints** - Provides maximum flexibility
3. **Use simple_mode for high-volume endpoints** - Reduces response size if needed
4. **Format currency on backend** - Reduces frontend complexity
5. **Include currency in list responses** - Even if all items have same currency
6. **Document currency handling** - Make it clear in API docs

## Common Patterns

### Pattern 1: Company Base Currency
All financial data in company's base currency (most common):
```python
total = MoneyField(max_digits=15, decimal_places=2, source_currency='KES')
```

### Pattern 2: Multi-Currency Support
Each record has its own currency:
```python
amount = MoneyField(max_digits=15, decimal_places=2, currency_field='currency')
```

### Pattern 3: Mixed Multi-Currency
Some fields static, some dynamic:
```python
# Order amounts in order's currency
order_total = MoneyField(max_digits=15, decimal_places=2, currency_field='currency')

# Processing fees always in KES
processing_fee = MoneyField(max_digits=10, decimal_places=2, source_currency='KES')
```

## Troubleshooting

### Currency Shows as 'KES' When It Should Be Different

**Problem:** MoneyField always returns 'KES' even though model has different currency.

**Solution:** Make sure the model instance has a `currency` field, or explicitly specify `currency_field`:

```python
# Automatic detection (model must have 'currency' field)
amount = MoneyField(max_digits=15, decimal_places=2)

# OR explicit field name
amount = MoneyField(max_digits=15, decimal_places=2, currency_field='order_currency')
```

### Getting Just a Number Instead of Object

**Problem:** API returns `1000.00` instead of `{ amount: 1000.00, currency: "KES", ... }`

**Solution:** Make sure `simple_mode=True` is not set:

```python
# Wrong
amount = MoneyField(max_digits=15, decimal_places=2, simple_mode=True)

# Correct
amount = MoneyField(max_digits=15, decimal_places=2)  # simple_mode defaults to False
```

### Frontend Can't Read Currency

**Problem:** Frontend code expects just a number but gets an object.

**Solution:** Use `.amount` property or update to simple_mode temporarily:

```javascript
// Option 1: Access amount property
const numericValue = response.total.amount;

// Option 2: Use enhanced format
const { amount, currency, formatted } = response.total;
```

## Testing

### Test Enhanced Format
```python
def test_money_field_enhanced_format():
    invoice = Invoice.objects.create(total=Decimal('1000.00'), currency='KES')
    serializer = InvoiceSerializer(invoice)

    assert serializer.data['total']['amount'] == '1000.00'
    assert serializer.data['total']['currency'] == 'KES'
    assert serializer.data['total']['formatted'] == 'KSh 1,000.00'
```

### Test Simple Mode
```python
def test_money_field_simple_mode():
    invoice = Invoice.objects.create(total=Decimal('1000.00'))

    class SimpleInvoiceSerializer(serializers.ModelSerializer):
        total = MoneyField(max_digits=15, decimal_places=2, simple_mode=True)
        class Meta:
            model = Invoice
            fields = ['total']

    serializer = SimpleInvoiceSerializer(invoice)
    assert serializer.data['total'] == '1000.00'  # Just the number
```

## See Also

- [Currency Usage Guide](../../erp-ui/src/composables/CURRENCY_USAGE_GUIDE.md) - Frontend currency handling
- [Currency Migration Guide](../../erp-ui/CURRENCY_MIGRATION_GUIDE.md) - Frontend migration steps
- [formatCurrency utilities](../../erp-ui/src/utils/formatters.js) - Frontend formatting functions
