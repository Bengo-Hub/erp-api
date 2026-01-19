# Unified Currency System - Backend & Frontend Sync

## Overview

The unified currency system provides a single source of truth for currency operations across the entire ERP system. It automatically syncs currency selection between frontend and backend, eliminating duplicate logic and ensuring consistent behavior.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Vue 3)                         │
│  ┌────────────────────────────────────────────────────┐    │
│  │  CurrencySwitcher Component                        │    │
│  │  - User selects currency (USD, EUR, KES, etc.)    │    │
│  │  - Saves to localStorage                           │    │
│  │  - Emits 'currency-changed' event                  │    │
│  └────────────────────┬───────────────────────────────┘    │
│                       │                                     │
│  ┌────────────────────▼───────────────────────────────┐    │
│  │  Axios Interceptor                                 │    │
│  │  - Reads selectedCurrency from localStorage        │    │
│  │  - Adds X-Currency header to ALL API requests      │    │
│  └────────────────────┬───────────────────────────────┘    │
└────────────────────────┼───────────────────────────────────┘
                         │
                         │ HTTP Request with X-Currency header
                         │
┌────────────────────────▼───────────────────────────────────┐
│                    Backend (Django)                         │
│  ┌────────────────────────────────────────────────────┐    │
│  │  CurrencyContextMiddleware                         │    │
│  │  - Reads X-Currency header from request            │    │
│  │  - Sets active currency in session                 │    │
│  │  - Sets active currency in thread-local context    │    │
│  │  - Adds request.active_currency attribute          │    │
│  └────────────────────┬───────────────────────────────┘    │
│                       │                                     │
│  ┌────────────────────▼───────────────────────────────┐    │
│  │  CurrencyService (core/currency.py)                │    │
│  │  - get_active_currency(request)  → 'USD'           │    │
│  │  - convert_to_active(1000, 'KES', request)         │    │
│  │  - format_amount(1000, active_currency)            │    │
│  └────────────────────┬───────────────────────────────┘    │
│                       │                                     │
│  ┌────────────────────▼───────────────────────────────┐    │
│  │  All Backend Modules                               │    │
│  │  - finance, invoicing, inventory, etc.             │    │
│  │  - Use CurrencyService.get_active_currency()       │    │
│  │  - Automatic conversion to user's currency         │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Backend - CurrencyService (Single Source of Truth)

**Location:** `core/currency.py`

**Core Features:**
- Context-aware active currency management
- Automatic currency conversion with exchange rates
- Formatting with proper symbols and decimal places
- Thread-safe with request-scoped context

**Usage Example:**
```python
from core.currency import CurrencyService
from decimal import Decimal

def my_view(request):
    # Get active currency from request context
    active_currency = CurrencyService.get_active_currency(request)
    # Returns: 'USD' (from X-Currency header)

    # Convert amount to active currency
    amount_kes = Decimal('1000.00')
    converted = CurrencyService.convert_to_active(amount_kes, 'KES', request)
    # Converts 1000 KES → 7.70 USD (using exchange rates)

    # Format in active currency
    formatted = CurrencyService.format_amount(converted, active_currency)
    # Returns: "$7.70"

    return Response({
        'amount': converted,
        'formatted': formatted,
        'currency': active_currency
    })
```

### 2. Backend - CurrencyContextMiddleware

**Location:** `core/middleware/currency_middleware.py`

**What it does:**
1. Intercepts ALL incoming requests
2. Reads `X-Currency` header sent by frontend
3. Sets active currency in session and thread-local context
4. Adds `request.active_currency` attribute for easy access
5. Adds `X-Active-Currency` response header for frontend sync

**Installation:**
Add to `settings.py` MIDDLEWARE:
```python
MIDDLEWARE = [
    # ... other middleware ...
    'core.middleware.CurrencyContextMiddleware',
    # ... other middleware ...
]
```

### 3. Frontend - Axios Interceptor

**Location:** `src/utils/axiosConfig.js`

**What it does:**
1. Intercepts ALL outgoing API requests
2. Reads `selectedCurrency` from localStorage
3. Adds `X-Currency` header automatically
4. Backend receives currency context without explicit passing

**How it works:**
```javascript
// When user switches currency in CurrencySwitcher:
localStorage.setItem('selectedCurrency', 'USD');

// Axios interceptor automatically adds to ALL requests:
headers: {
    'X-Currency': 'USD'  // ← Added automatically
}

// Backend receives request.active_currency = 'USD'
```

### 4. Frontend - Currency Composables

**Location:** `src/composables/useGlobalCurrency.js`

**Enhanced formatCurrencySync:**
```javascript
// Now supports source currency parameter
formatCurrencySync(amount, 'KES')  // Converts KES → Active Currency

// Defaults to KES if not specified (seamless migration!)
formatCurrencySync(amount)  // Assumes KES, converts to Active Currency
```

## How Currency Flows Through the System

### Scenario 1: User Switches Currency

```
1. User clicks currency switcher → Selects USD
   ↓
2. CurrencySwitcher.vue
   - Saves to localStorage: 'selectedCurrency' = 'USD'
   - Emits 'currency-changed' event
   ↓
3. All Dashboard Components (listening to event)
   - Reactive computed values auto-update
   - formatCurrencySync() re-runs with new currency
   ↓
4. Next API Request
   - Axios interceptor adds X-Currency: USD header
   ↓
5. Backend Middleware
   - Sets active_currency = 'USD' for this request
   ↓
6. Backend Views/Services
   - CurrencyService.get_active_currency(request) → 'USD'
   - All amounts auto-convert to USD
```

### Scenario 2: API Endpoint Returns Data

```
1. Backend View
   from core.currency import CurrencyService

   amount_kes = invoice.total  # 1000 KES
   active = CurrencyService.get_active_currency(request)  # 'USD'
   converted = CurrencyService.convert_to_active(amount_kes, 'KES', request)
   # Returns 7.70 USD

   ↓
2. Returns Response
   {
       "total": {
           "amount": 7.70,
           "currency": "USD",
           "formatted": "$7.70"
       }
   }
   ↓
3. Frontend Receives
   - Already in user's selected currency!
   - Can display formatted value directly
   - Or use amount for calculations
```

## Priority System for Active Currency

CurrencyService.get_active_currency() uses this priority:

1. **X-Currency header** (highest priority)
   - From frontend currency switcher
   - Synced automatically by axios

2. **Session stored currency**
   - Persisted across requests
   - Set by middleware when header received

3. **Thread-local active currency**
   - For background jobs/tasks
   - Set explicitly via set_active_currency()

4. **Business default currency**
   - From user's business settings
   - Fallback for authenticated users

5. **System default (KES)**
   - Ultimate fallback
   - Used when nothing else available

## Backend Usage Patterns

### Pattern 1: Simple View with Auto-Conversion

```python
from core.currency import CurrencyService
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['GET'])
def dashboard_stats(request):
    # Get active currency (automatically from request context)
    currency = CurrencyService.get_active_currency(request)

    # Get data in KES (base currency)
    revenue_kes = calculate_revenue()  # Returns Decimal('150000.00')
    expenses_kes = calculate_expenses()  # Returns Decimal('75000.00')

    # Convert to active currency
    revenue = CurrencyService.convert_to_active(revenue_kes, 'KES', request)
    expenses = CurrencyService.convert_to_active(expenses_kes, 'KES', request)

    # Return data (already in user's currency!)
    return Response({
        'revenue': {
            'amount': revenue,
            'currency': currency,
            'formatted': CurrencyService.format_amount(revenue, currency)
        },
        'expenses': {
            'amount': expenses,
            'currency': currency,
            'formatted': CurrencyService.format_amount(expenses, currency)
        }
    })
```

### Pattern 2: Using MoneyField Serializer

```python
from rest_framework import serializers
from core.serializer_fields import MoneyField

class InvoiceSerializer(serializers.ModelSerializer):
    # Automatically uses active currency from request context
    total = MoneyField(max_digits=15, decimal_places=2, source_currency='KES')

    class Meta:
        model = Invoice
        fields = ['id', 'invoice_number', 'total']
```

### Pattern 3: Background Job with Explicit Currency

```python
from core.currency import CurrencyService
from decimal import Decimal

def process_payment_job(payment_id):
    # Background jobs don't have request context
    # Set active currency explicitly
    CurrencyService.set_active_currency('USD')

    payment = Payment.objects.get(id=payment_id)

    # Convert to active currency
    amount_usd = CurrencyService.convert_to_active(payment.amount, payment.currency)

    # Process payment...

    # Clear context when done
    CurrencyService.clear_active_currency()
```

## Frontend Usage Patterns

### Pattern 1: Dashboard Stats (Automatic Conversion)

```javascript
import { useGlobalCurrency } from '@/composables/useGlobalCurrency';

const { formatCurrencySync } = useGlobalCurrency();

// Backend returns data in KES
const dashboardData = ref({ revenue: 150000, expenses: 75000 });

// Format with auto-conversion (assumes KES source)
const formattedRevenue = formatCurrencySync(() => dashboardData.value.revenue);
const formattedExpenses = formatCurrencySync(() => dashboardData.value.expenses);

// When user switches to USD:
// - formatCurrencySync detects currency change
// - Converts 150000 KES → 1155 USD (using exchange rate)
// - Displays "$1,155.00"
```

### Pattern 2: With Explicit Source Currency

```javascript
// Backend returns data with currency info
const invoice = {
    total: { amount: 500, currency: 'EUR' }
};

// Convert from EUR to active currency
const formatted = formatCurrencySync(
    invoice.total.amount,
    invoice.total.currency
);
```

### Pattern 3: Currency Switcher Component

```vue
<template>
    <Dropdown
        v-model="selectedCurrency"
        :options="currencies"
        @change="onCurrencyChange"
    />
</template>

<script setup>
import { useCurrency } from '@/composables/useCurrency';

const { selectedCurrency, setSelectedCurrency } = useCurrency();

const onCurrencyChange = () => {
    // Save to localStorage (axios interceptor will send to backend)
    setSelectedCurrency(selectedCurrency.value);

    // Emit event for components to update
    window.dispatchEvent(new CustomEvent('currency-changed', {
        detail: { currency: selectedCurrency.value }
    }));
};
</script>
```

## Migration Guide for Existing Code

### Backend Migration

**Before (Multiple currency utilities):**
```python
# finance/utils.py
from finance.currency_helper import convert_amount

# inventory/utils.py
from inventory.currency import format_with_symbol

# Different implementations everywhere!
```

**After (Single source of truth):**
```python
# Everywhere in the codebase
from core.currency import CurrencyService

# Same interface, same behavior
amount_converted = CurrencyService.convert_to_active(1000, 'KES', request)
formatted = CurrencyService.format_amount(amount_converted, request.active_currency)
```

### Frontend Migration

**Before (Static currency):**
```javascript
import { formatCurrency } from '@/utils/formatters';

// Hardcoded KES, never converts
const formatted = formatCurrency(1000, 'KES');
```

**After (Dynamic conversion):**
```javascript
import { useGlobalCurrency } from '@/composables/useGlobalCurrency';

const { formatCurrencySync } = useGlobalCurrency();

// Auto-converts based on selected currency
const formatted = formatCurrencySync(1000, 'KES');
```

## Testing

### Backend Test Example

```python
from django.test import TestCase, RequestFactory
from core.currency import CurrencyService
from decimal import Decimal

class CurrencyServiceTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_active_currency_from_header(self):
        # Create request with X-Currency header
        request = self.factory.get('/', HTTP_X_CURRENCY='USD')

        # Should read currency from header
        currency = CurrencyService.get_active_currency(request)
        self.assertEqual(currency, 'USD')

    def test_convert_to_active_currency(self):
        request = self.factory.get('/', HTTP_X_CURRENCY='USD')

        # Convert 1000 KES to USD
        converted = CurrencyService.convert_to_active(
            Decimal('1000.00'), 'KES', request
        )

        # Should be converted (exact value depends on exchange rate)
        self.assertNotEqual(converted, Decimal('1000.00'))
```

### Frontend Test Example

```javascript
import { mount } from '@vue/test-utils';
import { useGlobalCurrency } from '@/composables/useGlobalCurrency';

describe('formatCurrencySync', () => {
    it('converts from KES to USD', async () => {
        // Set active currency to USD
        localStorage.setItem('selectedCurrency', 'USD');

        const { formatCurrencySync } = useGlobalCurrency();

        // Format 1000 KES
        const formatted = formatCurrencySync(1000, 'KES');

        // Should be converted to USD
        await nextTick();
        expect(formatted.value).toContain('$');
        expect(formatted.value).not.toContain('1,000');
    });
});
```

## Troubleshooting

### Issue: Currency not syncing to backend

**Symptoms:** Backend always uses KES even though frontend shows USD.

**Solution:** Check if middleware is installed:
```python
# settings.py
MIDDLEWARE = [
    # ...
    'core.middleware.CurrencyContextMiddleware',  # ← Must be present
    # ...
]
```

### Issue: Axios not sending X-Currency header

**Symptoms:** Backend doesn't receive currency header.

**Solution:** Check if currency is saved to localStorage:
```javascript
// Should exist
const currency = localStorage.getItem('selectedCurrency');
console.log('Selected currency:', currency);  // Should show 'USD', 'EUR', etc.
```

### Issue: Exchange rates not working

**Symptoms:** Conversion always returns same amount (1:1 rate).

**Solution:** Check ExchangeRate model has data:
```python
from core.models import ExchangeRate

# Should have rates
rates = ExchangeRate.objects.filter(is_active=True)
print(rates)  # Should show rates like KES→USD, KES→EUR
```

## Benefits Summary

✅ **Single Source of Truth**
- One CurrencyService used by all modules
- No duplicate currency logic
- Consistent behavior everywhere

✅ **Automatic Sync**
- Frontend switcher → Backend context
- No manual currency passing needed
- Session persistence across requests

✅ **Developer Friendly**
- Simple API: `CurrencyService.get_active_currency(request)`
- Works with request context automatically
- Thread-safe for background jobs

✅ **User Friendly**
- Real-time currency conversion
- Seamless switching between currencies
- Consistent display across all pages

✅ **Maintainable**
- Update conversion logic in one place
- Easy to add new currencies
- Clear migration path for existing code

## Related Documentation

- [MoneyField Serializer Guide](./MONEY_FIELD_GUIDE.md)
- [Frontend Currency Usage Guide](../../erp-ui/src/composables/CURRENCY_USAGE_GUIDE.md)
- [Frontend Migration Guide](../../erp-ui/CURRENCY_MIGRATION_GUIDE.md)
