### Purpose

Define consistent, production-ready frontend rules for ERPUI that prevent duplication, enforce the service layer pattern, and align UI structure with the backend.

### Golden Rules

- **Zero duplication**: Always scan the entire project for existing pages, components, forms, tables, services, and composables before building anything new. Refactor existing files instead of creating new ones unless truly necessary.
- **No direct axios in components**: All HTTP calls must go through dedicated files under `src/services/`. Components and views must not import `axios` directly.
- **Single source of truth**: Centralize shared logic in services or composables; never fork logic across multiple files.
- **Vue 3 + PrimeVue only**: Use the existing stack; do not introduce new UI frameworks.
- **Keep it production-ready**: Avoid placeholders. Implement complete, working logic with error handling and loading states.

### Folder Structure and Naming

- **Components**: Reusable UI in `src/components/`. Generic, style-only building blocks live in `src/components/ui/`. Cross-feature helpers remain in `src/components/common/`.
- **Views**: Route pages in `src/views/` organized by domain (auth, dashboard, hrm, finance, ecommerce, crm, procurement, manufacturing, settings).
- **Services**: Domain-specific files in `src/services/` (e.g., `employeeService.js`, `financeService.js`).
- **Composables**: Reusable logic in `src/composables/`.
- **Store**: Vuex modules in `src/store/`.
- **Naming**:
  - Components: PascalCase (e.g., `PageHeader.vue`).
  - Services: camelCase exports in `*.js` (e.g., `financeService`).
  - Composables: `useSomething.js`.

### Service Layer Rules

- **One domain per service**: Group endpoints by business domain; do not duplicate endpoints across services.
- **Consistent operations**: Use standard method names for CRUD and queries.
- **Error handling**: Centralize consistent error handling; surface user-friendly messages at the component level.
- **Base URL**: Use the globally configured `axios.defaults.baseURL` set in `main.js`.
- **File uploads**: If specialized headers or streaming are needed, encapsulate them within the appropriate service.

### Component Rules

- **Stateless UI primitives**: Place generic UI building blocks under `src/components/ui/` (e.g., headers, empty states, search inputs). Keep them logic-light and slot-friendly.
- **Feature components**: Keep feature-specific components under their domain folders (e.g., `components/payroll/`), delegating data access to services.
- **Loading and errors**: Show loading indicators and toasts consistently; reuse existing `Spinner.vue` and `common/OfflineIndicator.vue` where applicable.

### Views and Routing

- **Views**: Views orchestrate feature components and services; they must not contain duplicate API logic.
- **Routing**: Keep routes organized by module under `src/router/` and reuse existing guards and patterns.

### Refactoring Policy

- **First refactor, then add**: If similar logic exists, refactor and generalize it instead of adding new files.
- **Backwards compatibility**: Preserve existing behavior while improving structure.
- **PrimeVue alignment**: Prefer PrimeVue components and patterns already configured in `main.js`.

### Backend Alignment

- **Endpoint mapping**: Ensure services map to existing Django endpoints by module and version (prefer v1 where available).
- **Shared data rules**: Reuse existing utilities for formatting, dates, and shared enums.

### Linting and Quality

- **ESLint**: Components and views must not import `axios` directly; use services instead.
- **Consistency**: Follow Prettier formatting and existing code style.

### When to Create New Files

- **Create** only when no suitable file exists and refactoring would clearly harm readability or separation of concerns.
- **Otherwise** refactor existing pages, components, forms, tables, composables, or services to extend behavior.


