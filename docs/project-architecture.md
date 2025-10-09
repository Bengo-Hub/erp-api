# Bengo ERP - Project Architecture & Refactoring Plan

## Executive Summary

This document outlines the proposed architecture for the Bengo ERP system, focusing on clean architecture principles, modular design, and scalability. The architecture is designed to support the Kenyan market requirements while maintaining clean separation of concerns and enabling future growth.

## 1. Current Architecture Analysis

### 1.1 Current Structure Issues

**Backend Issues:**
- Monolithic Django structure with tightly coupled modules
- Inconsistent naming conventions across modules
- Missing API versioning and proper REST conventions
- No clear separation between business logic and API layer
- Incomplete error handling and validation
- Missing comprehensive testing structure

**Frontend Issues:**
- Inconsistent component organization
- No clear service layer abstraction
- Missing state management patterns
- Incomplete routing structure
- No proper error boundaries
- Missing loading states and user feedback

### 1.2 Technical Debt Assessment

- **High Priority**: Missing API endpoints (60% of models)
- **High Priority**: Incomplete security implementation
- **Medium Priority**: Code duplication across modules
- **Medium Priority**: Inconsistent error handling
- **Low Priority**: Missing documentation

## 2. Proposed Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend Layer (Vue.js)                  │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────┐ │
│  │   Auth UI   │ │   HRM UI    │ │ Finance UI  │ │  ...    │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────┘ │
├─────────────────────────────────────────────────────────────┤
│                    API Gateway Layer                        │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────┐ │
│  │ Auth API    │ │ HRM API     │ │ Finance API │ │  ...    │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────┘ │
├─────────────────────────────────────────────────────────────┤
│                  Business Logic Layer                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────┐ │
│  │ Auth Service│ │ HRM Service │ │Finance Svc  │ │  ...    │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────┘ │
├─────────────────────────────────────────────────────────────┤
│                    Data Access Layer                        │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────┐ │
│  │ Auth Repo   │ │ HRM Repo    │ │ Finance Repo│ │  ...    │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────┘ │
├─────────────────────────────────────────────────────────────┤
│                    Infrastructure Layer                     │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────┐ │
│  │ PostgreSQL  │ │   Redis     │ │   Celery    │ │  ...    │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Backend Architecture (Django)

#### 2.2.1 Proposed Structure

```
ERPAPI/
├── apps/                           # Django Applications
│   ├── core/                      # Core functionality
│   │   ├── models/                # Shared models
│   │   ├── services/              # Shared services
│   │   ├── utils/                 # Shared utilities
│   │   └── exceptions/            # Custom exceptions
│   ├── auth/                      # Authentication & Authorization
│   │   ├── models/
│   │   ├── services/
│   │   ├── serializers/
│   │   ├── views/
│   │   └── urls.py
│   ├── hrm/                       # Human Resource Management
│   │   ├── employees/
│   │   ├── payroll/
│   │   ├── attendance/
│   │   ├── leave/
│   │   ├── performance/
│   │   ├── recruitment/
│   │   └── training/
│   ├── finance/                   # Financial Management
│   │   ├── accounts/
│   │   ├── payments/
│   │   ├── expenses/
│   │   ├── taxes/
│   │   ├── budgets/
│   │   └── banking/
│   ├── ecommerce/                 # E-commerce & POS
│   │   ├── products/
│   │   ├── inventory/
│   │   ├── orders/
│   │   ├── pos/
│   │   └── vendors/
│   ├── crm/                       # Customer Relationship Management
│   │   ├── contacts/
│   │   ├── leads/
│   │   ├── opportunities/
│   │   └── support/
│   ├── procurement/               # Procurement & Supply Chain
│   │   ├── requisitions/
│   │   ├── orders/
│   │   ├── suppliers/
│   │   └── contracts/
│   ├── manufacturing/             # Manufacturing & Production
│   │   ├── production/
│   │   ├── quality/
│   │   ├── work_orders/
│   │   └── materials/
│   └── integrations/              # Third-party Integrations
│       ├── payments/
│       ├── communications/
│       └── external_apis/
├── api/                           # API Layer
│   ├── v1/                        # API Version 1
│   │   ├── auth/
│   │   ├── hrm/
│   │   ├── finance/
│   │   ├── ecommerce/
│   │   ├── crm/
│   │   ├── procurement/
│   │   ├── manufacturing/
│   │   └── integrations/
│   ├── middleware/                # Custom middleware
│   ├── utils/                     # API utilities
│   └── docs/                      # API documentation
├── core/                          # Core project settings
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   ├── staging.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
├── shared/                        # Shared utilities
│   ├── base/                      # Base classes
│   ├── decorators/                # Custom decorators
│   ├── permissions/               # Custom permissions
│   └── validators/                # Custom validators
├── tests/                         # Test suite
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── docs/                          # Documentation
├── scripts/                       # Management scripts
├── requirements/                  # Requirements files
│   ├── base.txt
│   ├── development.txt
│   ├── staging.txt
│   └── production.txt
├── manage.py
└── README.md
```

#### 2.2.2 Module Isolation Strategy

**Independent Modules (Microservices Candidates):**
1. **Authentication Service** - User management, roles, permissions
2. **HRM Service** - Employee management, payroll, attendance
3. **Finance Service** - Accounting, payments, financial reporting
4. **E-commerce Service** - Product management, inventory, POS
5. **CRM Service** - Customer management, leads, opportunities
6. **Procurement Service** - Purchase management, suppliers
7. **Manufacturing Service** - Production planning, quality control
8. **Integration Service** - Third-party integrations

**Shared Components:**
- Core models and utilities
- Authentication and authorization
- Common business logic
- Shared data access patterns

### 2.3 Frontend Architecture (Vue.js)

#### 2.3.1 Proposed Structure

```
ERPUI/src/
├── components/                    # Reusable Components
│   ├── common/                   # Common UI components
│   │   ├── BaseButton.vue
│   │   ├── BaseInput.vue
│   │   ├── BaseModal.vue
│   │   └── BaseTable.vue
│   ├── forms/                    # Form components
│   │   ├── EmployeeForm.vue
│   │   ├── PayrollForm.vue
│   │   └── ProductForm.vue
│   ├── tables/                   # Data table components
│   │   ├── EmployeeTable.vue
│   │   ├── PayrollTable.vue
│   │   └── ProductTable.vue
│   ├── charts/                   # Chart components
│   │   ├── SalesChart.vue
│   │   ├── PayrollChart.vue
│   │   └── AttendanceChart.vue
│   └── layout/                   # Layout components
│       ├── Sidebar.vue
│       ├── Header.vue
│       └── Footer.vue
├── views/                        # Page Components
│   ├── auth/                     # Authentication pages
│   │   ├── Login.vue
│   │   ├── Register.vue
│   │   └── ForgotPassword.vue
│   ├── dashboard/                # Dashboard pages
│   │   ├── MainDashboard.vue
│   │   ├── HRDashboard.vue
│   │   └── FinanceDashboard.vue
│   ├── hrm/                      # HR management pages
│   │   ├── employees/
│   │   ├── payroll/
│   │   ├── attendance/
│   │   ├── leave/
│   │   ├── performance/
│   │   ├── recruitment/
│   │   └── training/
│   ├── finance/                  # Financial pages
│   │   ├── accounts/
│   │   ├── payments/
│   │   ├── expenses/
│   │   ├── taxes/
│   │   ├── budgets/
│   │   └── banking/
│   ├── ecommerce/                # E-commerce pages
│   │   ├── products/
│   │   ├── inventory/
│   │   ├── orders/
│   │   ├── pos/
│   │   └── vendors/
│   ├── crm/                      # CRM pages
│   │   ├── contacts/
│   │   ├── leads/
│   │   ├── opportunities/
│   │   └── support/
│   ├── procurement/              # Procurement pages
│   │   ├── requisitions/
│   │   ├── orders/
│   │   ├── suppliers/
│   │   └── contracts/
│   ├── manufacturing/            # Manufacturing pages
│   │   ├── production/
│   │   ├── quality/
│   │   ├── work_orders/
│   │   └── materials/
│   └── settings/                 # Settings pages
│       ├── Profile.vue
│       ├── Company.vue
│       └── System.vue
├── router/                       # Vue Router configuration
│   ├── index.js
│   ├── guards.js
│   └── routes/
│       ├── auth.js
│       ├── hrm.js
│       ├── finance.js
│       ├── ecommerce.js
│       ├── crm.js
│       ├── procurement.js
│       └── manufacturing.js
├── store/                        # Vuex store modules
│   ├── index.js
│   ├── modules/
│   │   ├── auth.js
│   │   ├── hrm.js
│   │   ├── finance.js
│   │   ├── ecommerce.js
│   │   ├── crm.js
│   │   ├── procurement.js
│   │   └── manufacturing.js
│   └── plugins/
├── services/                     # API service layer
│   ├── api.js                    # Base API client
│   ├── auth.js
│   ├── hrm.js
│   ├── finance.js
│   ├── ecommerce.js
│   ├── crm.js
│   ├── procurement.js
│   └── manufacturing.js
├── utils/                        # Utility functions
│   ├── constants.js
│   ├── helpers.js
│   ├── validators.js
│   ├── formatters.js
│   └── permissions.js
├── assets/                       # Static assets
│   ├── images/
│   ├── icons/
│   └── styles/
├── styles/                       # Global styles
│   ├── variables.scss
│   ├── mixins.scss
│   ├── components.scss
│   └── utilities.scss
├── locales/                      # Internationalization
│   ├── en.json
│   └── sw.json
├── plugins/                      # Vue plugins
│   ├── primevue.js
│   ├── axios.js
│   └── i18n.js
├── App.vue
└── main.js
```

## 3. Refactoring & Restructuring Plan

### 3.1 Phase 1: Backend Restructuring (Weeks 1-4)

#### 3.1.1 Week 1: Core Infrastructure
**Tasks:**
- [ ] Create new project structure
- [ ] Set up core models and base classes
- [ ] Implement shared utilities and decorators
- [ ] Create custom permissions system
- [ ] Set up proper settings management

**Deliverables:**
- New project structure
- Core models and base classes
- Shared utilities and permissions
- Environment-specific settings

#### 3.1.2 Week 2: Authentication Module
**Tasks:**
- [ ] Refactor authentication models
- [ ] Implement JWT authentication
- [ ] Create role-based access control
- [ ] Set up user management API
- [ ] Implement password policies

**Deliverables:**
- Complete authentication system
- JWT token management
- Role-based permissions
- User management API

#### 3.1.3 Week 3: HRM Module Refactoring
**Tasks:**
- [ ] Reorganize HRM models into sub-modules
- [ ] Implement proper API endpoints
- [ ] Create comprehensive serializers
- [ ] Add business logic services
- [ ] Implement data validation

**Deliverables:**
- Modular HRM structure
- Complete API endpoints
- Business logic services
- Data validation

#### 3.1.4 Week 4: Finance Module Refactoring
**Tasks:**
- [ ] Reorganize finance models
- [ ] Implement financial calculations
- [ ] Create accounting services
- [ ] Add tax computation logic
- [ ] Implement reporting services

**Deliverables:**
- Modular finance structure
- Financial calculation services
- Tax computation logic
- Reporting services

### 3.2 Phase 2: Frontend Restructuring (Weeks 5-8)

#### 3.2.1 Week 5: Core Frontend Infrastructure
**Tasks:**
- [ ] Set up new frontend structure
- [ ] Implement base components
- [ ] Create service layer abstraction
- [ ] Set up state management
- [ ] Implement routing structure

**Deliverables:**
- New frontend structure
- Base component library
- Service layer
- State management
- Routing system

#### 3.2.2 Week 6: Authentication & Dashboard
**Tasks:**
- [ ] Create authentication pages
- [ ] Implement login/logout flow
- [ ] Create dashboard components
- [ ] Add navigation system
- [ ] Implement user profile

**Deliverables:**
- Authentication UI
- Dashboard system
- Navigation
- User profile

#### 3.2.3 Week 7: HRM Frontend
**Tasks:**
- [ ] Create HRM page components
- [ ] Implement employee management UI
- [ ] Add payroll interface
- [ ] Create attendance tracking
- [ ] Implement leave management

**Deliverables:**
- HRM UI components
- Employee management
- Payroll interface
- Attendance tracking
- Leave management

#### 3.2.4 Week 8: Finance Frontend
**Tasks:**
- [ ] Create finance page components
- [ ] Implement accounting interface
- [ ] Add payment management
- [ ] Create financial reports
- [ ] Implement budget management

**Deliverables:**
- Finance UI components
- Accounting interface
- Payment management
- Financial reports
- Budget management

### 3.3 Phase 3: Integration & Testing (Weeks 9-12)

#### 3.3.1 Week 9: API Integration
**Tasks:**
- [ ] Connect frontend to new APIs
- [ ] Implement error handling
- [ ] Add loading states
- [ ] Create data validation
- [ ] Implement caching

**Deliverables:**
- API integration
- Error handling
- Loading states
- Data validation
- Caching system

#### 3.3.2 Week 10: Testing Implementation
**Tasks:**
- [ ] Write unit tests for backend
- [ ] Create integration tests
- [ ] Implement frontend tests
- [ ] Add end-to-end tests
- [ ] Set up CI/CD pipeline

**Deliverables:**
- Comprehensive test suite
- CI/CD pipeline
- Test coverage reports
- Automated testing

#### 3.3.3 Week 11: Security & Performance
**Tasks:**
- [ ] Implement security measures
- [ ] Add rate limiting
- [ ] Optimize database queries
- [ ] Implement caching
- [ ] Add monitoring

**Deliverables:**
- Security implementation
- Performance optimization
- Caching system
- Monitoring setup

#### 3.3.4 Week 12: Documentation & Deployment
**Tasks:**
- [ ] Create API documentation
- [ ] Write user documentation
- [ ] Set up deployment pipeline
- [ ] Create migration scripts
- [ ] Prepare production deployment

**Deliverables:**
- Complete documentation
- Deployment pipeline
- Migration scripts
- Production readiness

## 4. Detailed Refactoring Guidelines

### 4.1 Backend Refactoring

#### 4.1.1 Model Refactoring
```python
# Before: Monolithic model
class Employee(models.Model):
    # All employee fields in one model
    pass

# After: Modular approach
# apps/hrm/employees/models.py
class Employee(BaseModel):
    """Employee model with proper separation of concerns."""
    
    class Meta:
        db_table = 'hrm_employees'
        verbose_name = 'Employee'
        verbose_name_plural = 'Employees'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['employee_id']),
            models.Index(fields=['department', 'status']),
        ]
    
    # Core fields
    employee_id = models.CharField(max_length=20, unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    
    # Relationships
    department = models.ForeignKey('Department', on_delete=models.PROTECT)
    position = models.ForeignKey('Position', on_delete=models.PROTECT)
    
    # Status and audit
    status = models.CharField(max_length=20, choices=EMPLOYMENT_STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.employee_id})"
    
    def get_full_name(self):
        """Return the full name of the employee."""
        return f"{self.first_name} {self.last_name}"
    
    def is_active(self):
        """Check if employee is active."""
        return self.status == 'active'
```

#### 4.1.2 Service Layer Implementation
```python
# apps/hrm/employees/services.py
from typing import List, Optional
from django.db.models import Q
from apps.core.services import BaseService
from apps.hrm.employees.models import Employee
from apps.hrm.employees.serializers import EmployeeSerializer

class EmployeeService(BaseService):
    """Service layer for employee management."""
    
    def __init__(self):
        self.model = Employee
        self.serializer_class = EmployeeSerializer
    
    def get_employees(self, filters: dict = None, user=None) -> List[Employee]:
        """Get employees with optional filtering."""
        queryset = self.model.objects.select_related('department', 'position')
        
        if filters:
            queryset = self._apply_filters(queryset, filters)
        
        if user and not user.is_superuser:
            queryset = queryset.filter(department__in=user.departments.all())
        
        return queryset
    
    def create_employee(self, data: dict, user) -> Employee:
        """Create a new employee."""
        # Validate data
        self._validate_employee_data(data)
        
        # Create employee
        employee = self.model.objects.create(
            **data,
            created_by=user
        )
        
        # Send notifications
        self._send_employee_created_notification(employee)
        
        return employee
    
    def update_employee(self, employee_id: str, data: dict, user) -> Employee:
        """Update an existing employee."""
        employee = self.get_employee_by_id(employee_id)
        
        # Validate update permissions
        self._validate_update_permissions(employee, user)
        
        # Update employee
        for field, value in data.items():
            setattr(employee, field, value)
        
        employee.save()
        employee.updated_by = user
        employee.save()
        
        return employee
    
    def _validate_employee_data(self, data: dict):
        """Validate employee data."""
        if not data.get('employee_id', '').startswith('EMP'):
            raise ValueError("Employee ID must start with 'EMP'")
        
        if self.model.objects.filter(email=data.get('email')).exists():
            raise ValueError("Email already exists")
    
    def _apply_filters(self, queryset, filters: dict):
        """Apply filters to queryset."""
        if filters.get('search'):
            search_term = filters['search']
            queryset = queryset.filter(
                Q(first_name__icontains=search_term) |
                Q(last_name__icontains=search_term) |
                Q(employee_id__icontains=search_term) |
                Q(email__icontains=search_term)
            )
        
        if filters.get('department'):
            queryset = queryset.filter(department_id=filters['department'])
        
        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])
        
        return queryset
```

#### 4.1.3 API Layer Implementation
```python
# api/v1/hrm/employees/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.hrm.employees.models import Employee
from apps.hrm.employees.serializers import EmployeeSerializer
from apps.hrm.employees.services import EmployeeService
from apps.core.permissions import HasEmployeePermission

class EmployeeViewSet(viewsets.ModelViewSet):
    """Employee management API endpoints."""
    
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated, HasEmployeePermission]
    service_class = EmployeeService
    
    def get_queryset(self):
        """Get filtered queryset."""
        service = self.service_class()
        filters = self.request.query_params.dict()
        return service.get_employees(filters, self.request.user)
    
    def perform_create(self, serializer):
        """Create employee with service layer."""
        service = self.service_class()
        employee = service.create_employee(
            serializer.validated_data,
            self.request.user
        )
        serializer.instance = employee
    
    def perform_update(self, serializer):
        """Update employee with service layer."""
        service = self.service_class()
        employee = service.update_employee(
            serializer.instance.employee_id,
            serializer.validated_data,
            self.request.user
        )
        serializer.instance = employee
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate an inactive employee."""
        employee = self.get_object()
        service = self.service_class()
        service.activate_employee(employee, request.user)
        return Response({'status': 'Employee activated'})
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate an active employee."""
        employee = self.get_object()
        service = self.service_class()
        service.deactivate_employee(employee, request.user)
        return Response({'status': 'Employee deactivated'})
```

### 4.2 Frontend Refactoring

#### 4.2.1 Component Structure
```vue
<!-- components/common/BaseTable.vue -->
<template>
  <div class="base-table">
    <div v-if="loading" class="base-table__loading">
      <ProgressSpinner />
    </div>
    
    <DataTable
      v-else
      :value="data"
      :paginator="paginator"
      :rows="rows"
      :totalRecords="totalRecords"
      :loading="loading"
      :filters="filters"
      :globalFilterFields="globalFilterFields"
      @page="onPageChange"
      @sort="onSort"
      @filter="onFilter"
    >
      <template #header>
        <slot name="header">
          <div class="flex justify-content-between align-items-center">
            <h3 class="m-0">{{ title }}</h3>
            <div class="flex gap-2">
              <slot name="actions" />
            </div>
          </div>
        </slot>
      </template>
      
      <slot />
      
      <template #empty>
        <slot name="empty">
          <div class="text-center p-4">
            <i class="pi pi-inbox text-4xl text-gray-400 mb-2" />
            <p class="text-gray-500">{{ emptyMessage }}</p>
          </div>
        </slot>
      </template>
    </DataTable>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

// Props
const props = defineProps({
  data: {
    type: Array,
    default: () => []
  },
  loading: {
    type: Boolean,
    default: false
  },
  title: {
    type: String,
    default: ''
  },
  paginator: {
    type: Boolean,
    default: true
  },
  rows: {
    type: Number,
    default: 10
  },
  totalRecords: {
    type: Number,
    default: 0
  },
  filters: {
    type: Object,
    default: () => ({})
  },
  globalFilterFields: {
    type: Array,
    default: () => []
  },
  emptyMessage: {
    type: String,
    default: 'No data available'
  }
})

// Emits
const emit = defineEmits(['page', 'sort', 'filter'])

// Composables
const { t } = useI18n()

// Methods
const onPageChange = (event) => {
  emit('page', event)
}

const onSort = (event) => {
  emit('sort', event)
}

const onFilter = (event) => {
  emit('filter', event)
}
</script>

<style scoped lang="scss">
.base-table {
  &__loading {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 200px;
  }
}
</style>
```

#### 4.2.2 Service Layer Implementation
```javascript
// services/api.js
import axios from 'axios'
import { useAuthStore } from '@/store/modules/auth'

class ApiClient {
  constructor() {
    this.client = axios.create({
      baseURL: import.meta.env.VITE_API_BASE_URL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json'
      }
    })
    
    this.setupInterceptors()
  }
  
  setupInterceptors() {
    // Request interceptor
    this.client.interceptors.request.use(
      (config) => {
        const authStore = useAuthStore()
        if (authStore.token) {
          config.headers.Authorization = `Bearer ${authStore.token}`
        }
        return config
      },
      (error) => {
        return Promise.reject(error)
      }
    )
    
    // Response interceptor
    this.client.interceptors.response.use(
      (response) => {
        return response
      },
      (error) => {
        if (error.response?.status === 401) {
          const authStore = useAuthStore()
          authStore.logout()
        }
        return Promise.reject(error)
      }
    )
  }
  
  async get(url, config = {}) {
    return this.client.get(url, config)
  }
  
  async post(url, data = {}, config = {}) {
    return this.client.post(url, data, config)
  }
  
  async put(url, data = {}, config = {}) {
    return this.client.put(url, data, config)
  }
  
  async patch(url, data = {}, config = {}) {
    return this.client.patch(url, data, config)
  }
  
  async delete(url, config = {}) {
    return this.client.delete(url, config)
  }
}

export const apiClient = new ApiClient()
```

```javascript
// services/hrm.js
import { apiClient } from './api'

class HRMService {
  constructor() {
    this.baseUrl = '/api/v1/hrm'
  }
  
  // Employee management
  async getEmployees(params = {}) {
    try {
      const response = await apiClient.get(`${this.baseUrl}/employees`, { params })
      return response.data
    } catch (error) {
      throw this.handleError(error)
    }
  }
  
  async getEmployee(id) {
    try {
      const response = await apiClient.get(`${this.baseUrl}/employees/${id}`)
      return response.data
    } catch (error) {
      throw this.handleError(error)
    }
  }
  
  async createEmployee(employeeData) {
    try {
      const response = await apiClient.post(`${this.baseUrl}/employees`, employeeData)
      return response.data
    } catch (error) {
      throw this.handleError(error)
    }
  }
  
  async updateEmployee(id, employeeData) {
    try {
      const response = await apiClient.put(`${this.baseUrl}/employees/${id}`, employeeData)
      return response.data
    } catch (error) {
      throw this.handleError(error)
    }
  }
  
  async deleteEmployee(id) {
    try {
      const response = await apiClient.delete(`${this.baseUrl}/employees/${id}`)
      return response.data
    } catch (error) {
      throw this.handleError(error)
    }
  }
  
  // Payroll management
  async getPayrollRecords(params = {}) {
    try {
      const response = await apiClient.get(`${this.baseUrl}/payroll`, { params })
      return response.data
    } catch (error) {
      throw this.handleError(error)
    }
  }
  
  async processPayroll(payrollData) {
    try {
      const response = await apiClient.post(`${this.baseUrl}/payroll/process`, payrollData)
      return response.data
    } catch (error) {
      throw this.handleError(error)
    }
  }
  
  handleError(error) {
    if (error.response) {
      return new Error(error.response.data.message || 'API Error')
    }
    return error
  }
}

export const hrmService = new HRMService()
```

## 5. Microservices Migration Strategy

### 5.1 Phase 1: Modular Monolith (Months 1-3)
- Implement clean architecture within current monolith
- Separate business logic into services
- Create proper API boundaries
- Implement comprehensive testing

### 5.2 Phase 2: Service Extraction (Months 4-6)
- Extract authentication service
- Extract HRM service
- Extract finance service
- Implement service communication

### 5.3 Phase 3: Full Microservices (Months 7-9)
- Extract remaining services
- Implement API gateway
- Add service discovery
- Implement distributed tracing

### 5.4 Service Communication Strategy
```python
# Service communication using HTTP/REST
class ServiceClient:
    """Base class for service-to-service communication."""
    
    def __init__(self, service_url: str):
        self.service_url = service_url
        self.client = requests.Session()
    
    def get(self, endpoint: str, params: dict = None):
        """Make GET request to service."""
        url = f"{self.service_url}{endpoint}"
        response = self.client.get(url, params=params)
        return self._handle_response(response)
    
    def post(self, endpoint: str, data: dict = None):
        """Make POST request to service."""
        url = f"{self.service_url}{endpoint}"
        response = self.client.post(url, json=data)
        return self._handle_response(response)
    
    def _handle_response(self, response):
        """Handle service response."""
        if response.status_code == 200:
            return response.json()
        else:
            raise ServiceCommunicationError(f"Service error: {response.status_code}")
```

## 6. Implementation Guidelines

### 6.1 Code Reuse and Zero Redundancy

#### 6.1.1 Shared Components
```python
# shared/base/models.py
class BaseModel(models.Model):
    """Base model with common fields and methods."""
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, related_name='%(class)s_created')
    updated_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, related_name='%(class)s_updated')
    
    class Meta:
        abstract = True
    
    def save(self, *args, **kwargs):
        if not self.pk:
            self.created_by = getattr(self, '_current_user', None)
        self.updated_by = getattr(self, '_current_user', None)
        super().save(*args, **kwargs)
```

#### 6.1.2 Shared Services
```python
# shared/base/services.py
class BaseService:
    """Base service with common operations."""
    
    def __init__(self, model, serializer_class=None):
        self.model = model
        self.serializer_class = serializer_class
    
    def get_by_id(self, id):
        """Get object by ID."""
        try:
            return self.model.objects.get(id=id)
        except self.model.DoesNotExist:
            raise ObjectNotFoundError(f"{self.model.__name__} not found")
    
    def list(self, filters=None):
        """List objects with optional filtering."""
        queryset = self.model.objects.all()
        if filters:
            queryset = self._apply_filters(queryset, filters)
        return queryset
    
    def create(self, data, user=None):
        """Create new object."""
        if user:
            data['created_by'] = user
        return self.model.objects.create(**data)
    
    def update(self, id, data, user=None):
        """Update existing object."""
        obj = self.get_by_id(id)
        for field, value in data.items():
            setattr(obj, field, value)
        if user:
            obj.updated_by = user
        obj.save()
        return obj
    
    def delete(self, id):
        """Delete object."""
        obj = self.get_by_id(id)
        obj.delete()
        return True
```

### 6.2 Clean Architecture Implementation

#### 6.2.1 Domain Layer
```python
# apps/hrm/domain/entities.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Employee:
    """Employee domain entity."""
    
    id: int
    employee_id: str
    first_name: str
    last_name: str
    email: str
    department_id: int
    status: str
    created_at: datetime
    updated_at: datetime
    
    @property
    def full_name(self) -> str:
        """Get full name."""
        return f"{self.first_name} {self.last_name}"
    
    def is_active(self) -> bool:
        """Check if employee is active."""
        return self.status == 'active'
```

#### 6.2.2 Use Case Layer
```python
# apps/hrm/domain/usecases.py
from typing import List, Optional
from apps.hrm.domain.entities import Employee
from apps.hrm.domain.repositories import EmployeeRepository

class EmployeeUseCase:
    """Employee business logic."""
    
    def __init__(self, repository: EmployeeRepository):
        self.repository = repository
    
    def get_employees(self, filters: dict = None) -> List[Employee]:
        """Get employees with filtering."""
        return self.repository.get_employees(filters)
    
    def create_employee(self, employee_data: dict) -> Employee:
        """Create new employee."""
        # Validate business rules
        self._validate_employee_data(employee_data)
        
        # Create employee
        employee = self.repository.create_employee(employee_data)
        
        # Send notifications
        self._send_employee_created_notification(employee)
        
        return employee
    
    def _validate_employee_data(self, data: dict):
        """Validate employee data according to business rules."""
        if not data.get('employee_id', '').startswith('EMP'):
            raise ValueError("Employee ID must start with 'EMP'")
        
        if self.repository.email_exists(data.get('email')):
            raise ValueError("Email already exists")
    
    def _send_employee_created_notification(self, employee: Employee):
        """Send notification when employee is created."""
        # Implementation for notification
        pass
```

## 7. Migration Strategy

### 7.1 Database Migration
```python
# scripts/migrate_data.py
from django.core.management.base import BaseCommand
from apps.hrm.employees.models import Employee as NewEmployee
from old_app.models import Employee as OldEmployee

class Command(BaseCommand):
    help = 'Migrate employee data from old structure to new structure'
    
    def handle(self, *args, **options):
        self.stdout.write('Starting employee data migration...')
        
        # Migrate employees
        old_employees = OldEmployee.objects.all()
        
        for old_employee in old_employees:
            try:
                new_employee = NewEmployee.objects.create(
                    employee_id=old_employee.employee_id,
                    first_name=old_employee.first_name,
                    last_name=old_employee.last_name,
                    email=old_employee.email,
                    department_id=old_employee.department_id,
                    status=old_employee.status,
                    created_at=old_employee.created_at,
                    updated_at=old_employee.updated_at
                )
                self.stdout.write(f'Migrated employee: {new_employee.employee_id}')
            except Exception as e:
                self.stdout.write(f'Error migrating employee {old_employee.employee_id}: {e}')
        
        self.stdout.write('Employee migration completed!')
```

### 7.2 Frontend Migration
```javascript
// scripts/migrate-frontend.js
import { migrateComponents } from './migration-utils'

// Migration script for frontend components
export async function migrateFrontend() {
  console.log('Starting frontend migration...')
  
  // Migrate components to new structure
  await migrateComponents()
  
  // Update routing
  await updateRouting()
  
  // Update services
  await updateServices()
  
  console.log('Frontend migration completed!')
}

async function migrateComponents() {
  // Implementation for component migration
}

async function updateRouting() {
  // Implementation for routing updates
}

async function updateServices() {
  // Implementation for service updates
}
```

## 8. Success Metrics

### 8.1 Technical Metrics
- **Code Coverage**: >90% for critical business logic
- **API Response Time**: <200ms for 95% of requests
- **Error Rate**: <0.1% for production
- **Security Score**: >95% (based on security scans)
- **Performance Score**: >90% (Lighthouse)

### 8.2 Business Metrics
- **Development Velocity**: 20% improvement in feature delivery
- **Bug Reduction**: 50% reduction in production bugs
- **Code Maintainability**: Improved maintainability scores
- **Team Productivity**: 30% improvement in development efficiency

### 8.3 Quality Metrics
- **Code Duplication**: <5% code duplication
- **Technical Debt**: Reduced technical debt by 60%
- **Documentation Coverage**: 100% API documentation
- **Test Automation**: 100% automated testing

## 9. Risk Mitigation

### 9.1 Technical Risks
- **Data Loss**: Implement comprehensive backup strategy
- **Service Downtime**: Use blue-green deployment
- **Performance Issues**: Implement performance monitoring
- **Security Vulnerabilities**: Regular security audits

### 9.2 Business Risks
- **Timeline Delays**: Agile development with sprints
- **Resource Constraints**: Proper resource allocation
- **Scope Creep**: Clear requirements and change management
- **User Adoption**: Comprehensive training and support

## 10. Conclusion

This comprehensive architecture plan provides a roadmap for transforming the Bengo ERP system into a modern, scalable, and maintainable application. The modular approach ensures clean separation of concerns while enabling future microservices migration.

The refactoring plan is designed to minimize disruption while maximizing code quality and developer productivity. By following these guidelines, the team can achieve a production-ready system that meets the needs of the Kenyan market while maintaining long-term scalability and maintainability.

**Next Steps:**
1. Begin Phase 1 implementation immediately
2. Set up development environment with new structure
3. Start with core infrastructure and authentication
4. Implement comprehensive testing from the beginning
5. Regular code reviews and quality checks

This architecture will serve as the foundation for a world-class ERP system that can compete effectively in the Kenyan market and beyond.
