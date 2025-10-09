# Role-Based Access Control (RBAC) Implementation

## Overview

The Bengo ERP system implements a comprehensive Role-Based Access Control (RBAC) system that maps Django permissions to frontend navigation and component access. This system ensures that users only see and can access features they have permission to use.

## Permission Structure

### Permission Format
All permissions follow Django's standard format: `{action}_{model}`
- **Actions**: `add_`, `change_`, `delete_`, `view_`
- **Models**: Specific model names like `employee`, `payroll`, `transaction`, etc.

### Permission Categories

#### HRM Module
- **Employee Management**: `view_employee`, `add_employee`, `change_employee`, `delete_employee`
- **Payroll**: `view_payrollcomponents`, `view_payslip`, `change_payslip`, `view_advances`
- **Leave Management**: `view_leaverequest`, `view_leavebalance`, `view_leaveentitlement`
- **Training**: `view_trainingcourse`, `view_trainingenrollment`, `view_trainingevaluation`
- **Appraisals**: `view_appraisal`, `view_appraisalquestion`, `view_appraisaltemplate`

#### Finance Module
- **Transactions**: `view_transaction`, `add_transaction`, `change_transaction`, `delete_transaction`
- **Accounts**: `view_paymentaccounts`, `add_paymentaccounts`, `change_paymentaccounts`
- **Vouchers**: `view_voucher`, `add_voucher`, `change_voucher`, `delete_voucher`
- **Taxes**: `view_tax`, `view_taxrates`, `add_tax`, `change_tax`
- **Budgets**: `view_budget`, `add_budget`, `change_budget`, `delete_budget`

#### CRM Module
- **Leads**: `view_lead`, `add_lead`, `change_lead`, `delete_lead`
- **Contacts**: `view_contact`, `add_contact`, `change_contact`, `delete_contact`
- **Deals**: `view_deal`, `add_deal`, `change_deal`, `delete_deal`
- **Campaigns**: `view_campaign`, `add_campaign`, `change_campaign`, `delete_campaign`

#### E-commerce Module
- **Sales**: `view_sales`, `add_sales`, `change_sales`, `delete_sales`
- **Products**: `view_products`, `add_products`, `change_products`, `delete_products`
- **Categories**: `view_category`, `add_category`, `change_category`, `delete_category`

#### Inventory Module
- **Stock**: `view_stockinventory`, `view_stocktransfer`, `view_stockadjustment`
- **Transfers**: `view_stocktransfer`, `add_stocktransfer`, `change_stocktransfer`
- **Adjustments**: `view_stockadjustment`, `add_stockadjustment`, `change_stockadjustment`

#### Manufacturing Module
- **Production**: `view_productionbatch`, `add_productionbatch`, `change_productionbatch`
- **Formulas**: `view_formulas`, `add_formulas`, `change_formulas`, `delete_formulas`
- **Quality**: `view_qualitycheck`, `add_qualitycheck`, `change_qualitycheck`

#### Procurement Module
- **Requisitions**: `view_procurementrequest`, `add_procurementrequest`, `change_procurementrequest`
- **Orders**: `view_purchaseorder`, `add_purchaseorder`, `change_purchaseorder`
- **Purchases**: `view_purchase`, `add_purchase`, `change_purchase`, `delete_purchase`
- **Suppliers**: `view_vendor`, `add_vendor`, `change_vendor`, `delete_vendor`

#### System Module
- **Users**: `view_customuser`, `add_customuser`, `change_customuser`, `delete_customuser`
- **Roles**: `view_group`, `add_group`, `change_group`, `delete_group`
- **Settings**: `view_appsettings`, `change_appsettings`
- **Backups**: `view_backup`, `add_backup`, `change_backup`, `delete_backup`

## Implementation Components

### 1. Permission Service (`src/services/auth/permissionService.js`)

The core service that provides permission checking utilities:

```javascript
import { hasPermission, hasAnyPermission, hasAllPermissions } from '@/services/auth/permissionService';

// Check single permission
if (hasPermission(userPermissions, 'view_employee')) {
    // User can view employees
}

// Check if user has any of multiple permissions
if (hasAnyPermission(userPermissions, ['view_employee', 'add_employee'])) {
    // User can view or add employees
}

// Check if user has all permissions
if (hasAllPermissions(userPermissions, ['view_employee', 'add_employee'])) {
    // User can both view and add employees
}
```

### 2. Permission Composable (`src/composables/usePermissions.js`)

Reactive permission checking for Vue components:

```javascript
import { usePermissions } from '@/composables/usePermissions';

export default {
    setup() {
        const { 
            can, 
            canAny, 
            canAll, 
            hasHrmAccess, 
            canManageEmployees 
        } = usePermissions();

        // Check specific permission
        const canViewEmployees = can('view_employee');
        
        // Check module access
        const hasHrm = hasHrmAccess.value;
        
        // Check common permissions
        const canManage = canManageEmployees.value;

        return {
            canViewEmployees,
            hasHrm,
            canManage
        };
    }
};
```

### 3. Permission Guard Component (`src/components/auth/PermissionGuard.vue`)

Component-level permission protection:

```vue
<template>
    <PermissionGuard permission="view_employee">
        <EmployeeList />
    </PermissionGuard>
    
    <PermissionGuard 
        :anyPermission="['view_employee', 'add_employee']"
        :showFallback="true"
        redirect-to="/dashboard"
    >
        <EmployeeManagement />
    </PermissionGuard>
</template>

<script setup>
import PermissionGuard from '@/components/auth/PermissionGuard.vue';
</script>
```

### 4. AppMenu Integration

The navigation menu automatically filters based on user permissions:

```javascript
// Menu items are automatically filtered based on permissions
const filterMenuItems = (menuItems, userPermissions) => {
    return menuItems
        .map((item) => {
            if (item.permission) {
                return hasPermission(userPermissions, item.permission) ? item : null;
            }
            return item;
        })
        .filter(Boolean);
};
```

## Usage Examples

### 1. Component-Level Permission Checking

```vue
<template>
    <div>
        <!-- Show based on single permission -->
        <div v-if="can('view_employee')">
            <EmployeeList />
        </div>
        
        <!-- Show based on any permission -->
        <div v-if="canAny(['view_employee', 'add_employee'])">
            <EmployeeActions />
        </div>
        
        <!-- Show based on module access -->
        <div v-if="hasHrmAccess">
            <HrmDashboard />
        </div>
    </div>
</template>

<script setup>
import { usePermissions } from '@/composables/usePermissions';

const { can, canAny, hasHrmAccess } = usePermissions();
</script>
```

### 2. Route Protection

```javascript
// In router configuration
{
    path: '/hrm/employees',
    component: () => import('@/views/hrm/EmployeeList.vue'),
    meta: {
        requiresAuth: true,
        requiredPermissions: ['view_employee']
    }
}

// Route guard
router.beforeEach((to, from, next) => {
    if (to.meta.requiredPermissions) {
        const user = store.state.auth.user;
        const hasPermission = to.meta.requiredPermissions.some(
            permission => user.permissions.includes(permission)
        );
        
        if (!hasPermission) {
            next('/access-denied');
            return;
        }
    }
    next();
});
```

### 3. API Service Permission Checking

```javascript
// In service files
export const employeeService = {
    getEmployees: async () => {
        // Check permission before making API call
        if (!can('view_employee')) {
            throw new Error('Insufficient permissions');
        }
        return axios.get('/api/employees/');
    },
    
    createEmployee: async (employeeData) => {
        if (!can('add_employee')) {
            throw new Error('Insufficient permissions');
        }
        return axios.post('/api/employees/', employeeData);
    }
};
```

### 4. Conditional UI Rendering

```vue
<template>
    <div class="employee-actions">
        <!-- View button - always visible if user has view permission -->
        <Button 
            v-if="can('view_employee')"
            label="View" 
            icon="pi pi-eye" 
            @click="viewEmployee" 
        />
        
        <!-- Edit button - only visible if user has change permission -->
        <Button 
            v-if="can('change_employee')"
            label="Edit" 
            icon="pi pi-pencil" 
            @click="editEmployee" 
        />
        
        <!-- Delete button - only visible if user has delete permission -->
        <Button 
            v-if="can('delete_employee')"
            label="Delete" 
            icon="pi pi-trash" 
            @click="deleteEmployee" 
            class="p-button-danger" 
        />
    </div>
</template>
```

## Best Practices

### 1. Permission Granularity
- Use specific permissions rather than broad ones
- Check permissions at the component level, not just routes
- Implement permission checking in API services

### 2. User Experience
- Hide UI elements users can't access rather than showing error messages
- Provide clear feedback when access is denied
- Use fallback content for permission-guarded sections

### 3. Security
- Always verify permissions on both frontend and backend
- Use the permission service consistently across the application
- Log permission-related actions for audit purposes

### 4. Performance
- Cache permission checks when possible
- Use computed properties for reactive permission checking
- Avoid checking permissions in loops or frequently called functions

## Testing Permissions

### 1. Development Testing
```javascript
// Mock user permissions for testing
const mockUser = {
    permissions: ['view_employee', 'add_employee', 'view_payroll']
};

// Test permission functions
console.log(hasPermission(mockUser.permissions, 'view_employee')); // true
console.log(hasPermission(mockUser.permissions, 'delete_employee')); // false
console.log(hasAnyPermission(mockUser.permissions, ['view_employee', 'delete_employee'])); // true
```

### 2. Component Testing
```javascript
// Test component with different permission sets
const wrapper = mount(EmployeeList, {
    global: {
        mocks: {
            $store: {
                state: {
                    auth: {
                        user: { permissions: ['view_employee'] }
                    }
                }
            }
        }
    }
});

expect(wrapper.find('.employee-list').exists()).toBe(true);
```

## Troubleshooting

### Common Issues

1. **Menu items not showing**: Check if permissions are properly mapped in AppMenu.vue
2. **Permission checks failing**: Verify user permissions are loaded in the store
3. **Route access denied**: Ensure route meta includes required permissions
4. **Component not rendering**: Check if PermissionGuard is properly configured

### Debug Tools

```javascript
// Add to components for debugging
const { userPermissions, permissionsByCategory } = usePermissions();

console.log('User Permissions:', userPermissions.value);
console.log('Permissions by Category:', permissionsByCategory.value);
```

## Future Enhancements

1. **Dynamic Permission Loading**: Load permissions from API instead of session storage
2. **Permission Inheritance**: Implement role-based permission inheritance
3. **Audit Logging**: Track permission usage and access attempts
4. **Permission Groups**: Group related permissions for easier management
5. **Temporary Permissions**: Time-based permission grants for specific tasks
