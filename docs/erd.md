# erp-api Entity-Relationship Documentation (Go / Ent)

> Authoritative ERD for the **Go rebuild** — generated from the Ent schemas in
> `internal/ent/schema/*.go`. The ERP is **HR/Ops only**: all decomposed domains
> (finance/treasury, inventory/products/stock, crm, ordering/cart, pos, notifications
> templates, auth identity, **projects/tenders**, **address_book/pickup_station/service_type**,
> **bank masters**) live in their owning services and are **not** modeled here (plan §0a).
>
> Conventions: every business table has a `uuid id` PK and (where tenant-owned) a
> `tenant_id uuid` for isolation; money is `decimal` (numeric), never float; timestamps are
> `timestamptz`. auth identity/tenants/outlets are shadows synced from auth-api.

Cross-cutting FK hubs:
- `Employee` — the HR aggregate root; most HR tables reference it by `employee_id`.
- `AuthTenant` / `AuthOutlet` — auth-api shadows (NATS-synced); everything is scoped by `tenant_id`.
- `CustomUser` — thin SSO user shadow (creator/approver/assignee references).

---

## 1. Auth shadows + RBAC (`custom_user`, `auth_tenant`, `auth_outlet`, `role`, `permission`, `role_permission`, `user_role_assignment`)

```mermaid
erDiagram
  AuthTenant ||--o{ AuthOutlet : "tenant_id"
  Role ||--o{ RolePermission : grants
  Permission ||--o{ RolePermission : in
  Role ||--o{ UserRoleAssignment : assigned
  CustomUser ||--o{ UserRoleAssignment : holds

  CustomUser { uuid id PK; string external_id "JWT sub"; string email; string first_name; string last_name; uuid tenant_id }
  AuthTenant { uuid id PK "auth-api UUID"; string slug; string name; bool is_platform; string status }
  AuthOutlet { uuid id PK "auth-api UUID"; uuid tenant_id FK; string code; string name; bool is_hq; string status }
  Role { uuid id PK; uuid tenant_id "NULL=global"; string role_code; string name; bool is_system_role }
  Permission { uuid id PK; string permission_code UK; string module; string action }
  RolePermission { uuid role_id FK; uuid permission_id FK }
  UserRoleAssignment { uuid id PK; uuid tenant_id; uuid user_id FK; uuid role_id FK }
```

RBAC permission codes + system roles are seeded by `cmd/seed` (`erp_admin`, `hr_manager`,
`payroll_manager`, `hr_viewer`); per-tenant assignment is derived from auth-api JWT roles
via `/auth/me` sync.

---

## 2. Employees (the HR FK hub)

```mermaid
erDiagram
  Employee ||--o| HRDetails : has
  Employee ||--o| SalaryDetails : has
  Employee ||--o| ContactDetails : has
  Employee ||--o{ NextOfKin : has
  Employee ||--o{ EmployeeDocument : has
  Employee ||--o{ EmployeeBankAccount : has
  Employee ||--o| Contract : has
  JobTitle ||--o{ HRDetails : titles
  JobGroup ||--o{ SalaryDetails : grades
  Department ||--o{ HRDetails : org
  WorkersUnion ||--o{ Employee : member

  Employee { uuid id PK; uuid tenant_id; uuid outlet_id; uuid user_id; string employee_number; string first_name; string last_name; string national_id; string pin_no "KRA PIN"; string shif_or_nhif_number; string nssf_no; bool terminated; bool deleted }
  HRDetails { uuid id PK; uuid tenant_id; uuid employee_id FK; uuid job_title_id; uuid department_id; uuid head_of_department_id "dept-head approver"; uuid reports_to_id "manager approver"; uuid region_id; string employment_type }
  SalaryDetails { uuid id PK; uuid tenant_id; uuid employee_id FK; decimal monthly_salary; decimal hourly_rate; decimal daily_rate; string pay_mode; string currency }
  ContactDetails { uuid id PK; uuid tenant_id; uuid employee_id FK; string phone; string email; string physical_address "HR-owned employee address" }
  NextOfKin { uuid id PK; uuid tenant_id; uuid employee_id FK; string name; string relationship; string phone }
  EmployeeDocument { uuid id PK; uuid tenant_id; uuid employee_id FK; string doc_type; string file_url }
  EmployeeBankAccount { uuid id PK; uuid tenant_id; uuid employee_id FK; string bank_name; string bank_code; string branch_name; string branch_code; string account_number; bool is_primary }
  Contract { uuid id PK; uuid tenant_id; uuid employee_id FK; string contract_type; date start_date; date end_date }
  JobTitle { uuid id PK; uuid tenant_id; string title }
  JobGroup { uuid id PK; uuid tenant_id; string name }
  Department { uuid id PK; uuid tenant_id; string title; uuid parent_department_id }
  WorkersUnion { uuid id PK; uuid tenant_id; string name }
```

> Bank details are **plain fields** on `EmployeeBankAccount` — there is **no** ERP-owned
> bank_institution/bank_branch master (banks = treasury/payment-rail reference, plan §0a).
> `HRDetails` has **no** `project_id` (projects-service owns projects).

---

## 3. Payroll + payroll settings (ERP-owned Kenyan statutory engine)

```mermaid
erDiagram
  Employee ||--o{ Payslip : earns
  Payslip ||--o{ PayslipAudit : audited
  Employee ||--o{ EmployeeLoan : owes
  Employee ||--o{ Advance : owes
  Employee ||--o{ LossAndDamage : owes
  Employee ||--o{ EmployeeBenefit : receives
  Employee ||--o{ ExpenseClaim : files
  ExpenseClaim ||--o{ ClaimItem : lines
  EmployeeLoan ||--o{ RepayOption : repays
  LoanType ||--o{ EmployeeLoan : typed
  PayrollFormula ||--o{ PayrollFormulaItem : bands
  PayrollFormula ||--o{ PayrollSplitRatio : tiers

  Payslip { uuid id PK; uuid tenant_id; uuid outlet_id; uuid employee_id FK; decimal gross_pay; decimal taxable_pay; decimal paye; decimal tax_relief; decimal shif_or_nhif_contribution; decimal housing_levy; decimal nssf_employee_tier_1; decimal nssf_employee_tier_2; decimal nssf_employer_contribution; decimal net_pay; date payment_period; string payroll_status; string approval_status; bool published; string batch_ref }
  PayslipAudit { uuid id PK; uuid tenant_id; uuid payslip_id FK; string action; json snapshot }
  PayrollComponent { uuid id PK; uuid tenant_id; string name; string deduction_phase; int priority }
  PayrollFormula { uuid id PK; uuid tenant_id; string name; date effective_from; json deduction_order }
  PayrollFormulaItem { uuid id PK; uuid formula_id FK; decimal lower; decimal upper; decimal rate }
  PayrollSplitRatio { uuid id PK; uuid formula_id FK; decimal threshold; decimal rate }
  PayrollRelief { uuid id PK; uuid tenant_id; string name; decimal amount; date effective_from }
  WithholdingTax { uuid id PK; uuid tenant_id; decimal rate }
  BenefitTax { uuid id PK; uuid tenant_id; string name; decimal rate }
  GeneralHRSettings { uuid id PK; uuid tenant_id; json settings }
  EmployeeLoan { uuid id PK; uuid tenant_id; uuid employee_id FK; uuid loan_type_id; decimal principal; decimal outstanding; string method }
  LoanType { uuid id PK; uuid tenant_id; string name }
  RepayOption { uuid id PK; uuid loan_id FK; decimal amount }
  Advance { uuid id PK; uuid tenant_id; uuid employee_id FK; decimal amount; decimal outstanding }
  LossAndDamage { uuid id PK; uuid tenant_id; uuid employee_id FK; decimal amount; decimal outstanding }
  EmployeeBenefit { uuid id PK; uuid tenant_id; uuid employee_id FK; decimal value; bool is_cash }
  ExpenseClaim { uuid id PK; uuid tenant_id; uuid employee_id FK; decimal total; string status }
  ClaimItem { uuid id PK; uuid claim_id FK; string description; decimal amount }
```

Payroll taxes (PAYE bands/relief, NSSF tiers, SHIF/NHIF, housing levy) are **ERP-owned**
(plan §7.3), data-driven via `PayrollFormula`/`PayrollFormulaItem`/`PayrollSplitRatio`.

---

## 4. Leave (`leave_category`, `leave_entitlement`, `leave_balance`, `leave_request`, `leave_log`, `public_holiday`)

```mermaid
erDiagram
  LeaveCategory ||--o{ LeaveEntitlement : grants
  LeaveCategory ||--o{ LeaveBalance : tracks
  LeaveCategory ||--o{ LeaveRequest : files
  LeaveRequest ||--o{ LeaveLog : audited
  Employee ||--o{ LeaveRequest : files

  LeaveCategory { uuid id PK; uuid tenant_id; string name; decimal default_annual_days; bool allow_carryover; decimal max_carryover_days }
  LeaveEntitlement { uuid id PK; uuid tenant_id; uuid employee_id; uuid category_id FK; int year; decimal days_entitled }
  LeaveBalance { uuid id PK; uuid tenant_id; uuid employee_id; uuid category_id FK; int year; decimal days_entitled; decimal days_taken; decimal days_remaining }
  LeaveRequest { uuid id PK; uuid tenant_id; uuid employee_id FK; uuid category_id FK; date start_date; date end_date; decimal days_requested; enum status }
  LeaveLog { uuid id PK; uuid tenant_id; uuid leave_request_id FK; enum action; string description }
  PublicHoliday { uuid id PK; uuid tenant_id; string name; date date; bool is_national; string county }
```

Leave decisions route through the **approvals engine** when a `leave_request` workflow is
configured (else direct pending→approved/rejected).

---

## 5. Attendance + shifts (`work_shift`(+`work_shift_schedule`), `attendance_record`, `attendance_rule`, `shift_rotation`, `shift_roster`(+`shift_roster_slot`), `shift_assignment`, `staff_shift_override`, `off_day`, `timesheet`(+`timesheet_entry`), `ess_settings`)

```mermaid
erDiagram
  WorkShift ||--o{ WorkShiftSchedule : days
  WorkShift ||--o{ ShiftAssignment : assigns
  Employee ||--o{ AttendanceRecord : clocks
  Employee ||--o{ Timesheet : submits
  Timesheet ||--o{ TimesheetEntry : lines
  ShiftRoster ||--o{ ShiftRosterSlot : slots

  WorkShift { uuid id PK; uuid tenant_id; string name; time start_time; time end_time }
  WorkShiftSchedule { uuid id PK; uuid shift_id FK; int weekday; bool working }
  AttendanceRecord { uuid id PK; uuid tenant_id; uuid employee_id FK; date date; datetime clock_in; datetime clock_out; string status }
  AttendanceRule { uuid id PK; uuid tenant_id; int grace_minutes; decimal overtime_rate }
  ShiftRotation { uuid id PK; uuid tenant_id; string name; json pattern }
  ShiftRoster { uuid id PK; uuid tenant_id; date period_start; date period_end }
  ShiftRosterSlot { uuid id PK; uuid roster_id FK; uuid employee_id; uuid shift_id; date date }
  ShiftAssignment { uuid id PK; uuid tenant_id; uuid employee_id; uuid shift_id FK }
  StaffShiftOverride { uuid id PK; uuid tenant_id; uuid employee_id; date date; uuid shift_id }
  OffDay { uuid id PK; uuid tenant_id; uuid employee_id; date date }
  Timesheet { uuid id PK; uuid tenant_id; uuid employee_id FK; date period_start; string status }
  TimesheetEntry { uuid id PK; uuid timesheet_id FK; date date; decimal hours; uuid project_id "free-form time tag" }
  ESSSettings { uuid id PK; uuid tenant_id; json self_service_settings }
```

---

## 6. Recruitment + onboarding + training (`job_posting`, `candidate`, `application`, `employee_onboarding`, `onboarding_task`, `training_course`, `training_enrollment`, `training_evaluation`)

```mermaid
erDiagram
  JobPosting ||--o{ Application : receives
  Candidate ||--o{ Application : applies
  Application ||--o| Employee : hires
  Employee ||--o| EmployeeOnboarding : onboards
  EmployeeOnboarding ||--o{ OnboardingTask : tasks
  TrainingCourse ||--o{ TrainingEnrollment : enrolls
  TrainingEnrollment ||--o| TrainingEvaluation : evaluated

  JobPosting { uuid id PK; uuid tenant_id; string title; string status }
  Candidate { uuid id PK; uuid tenant_id; string full_name; string email; string resume_url "media key or external link" }
  Application { uuid id PK; uuid tenant_id; uuid job_id FK; uuid candidate_id FK; string status; uuid hired_employee_id }
  EmployeeOnboarding { uuid id PK; uuid tenant_id; uuid employee_id FK; string status }
  OnboardingTask { uuid id PK; uuid tenant_id; uuid onboarding_id FK; string title; bool done }
  TrainingCourse { uuid id PK; uuid tenant_id; string name }
  TrainingEnrollment { uuid id PK; uuid tenant_id; uuid course_id FK; uuid employee_id; string status }
  TrainingEvaluation { uuid id PK; uuid enrollment_id FK; decimal score }
```

---

## 7. Appraisals + performance (`appraisal_cycle`, `appraisal_template`(+`appraisal_question`), `appraisal`(+`appraisal_response`), `goal`(+`goal_progress`), `metric_category`, `performance_metric`, `employee_metric`, `metric_target`, `performance_review`, `review_metric`)

```mermaid
erDiagram
  AppraisalCycle ||--o{ Appraisal : groups
  AppraisalTemplate ||--o{ AppraisalQuestion : has
  Appraisal ||--o{ AppraisalResponse : answers
  Employee ||--o{ Appraisal : reviewed
  Employee ||--o{ Goal : owns
  Goal ||--o{ GoalProgress : updates
  MetricCategory ||--o{ PerformanceMetric : groups
  PerformanceMetric ||--o{ EmployeeMetric : measures
  PerformanceReview ||--o{ ReviewMetric : scores

  AppraisalCycle { uuid id PK; uuid tenant_id; string name; date start_date; date end_date; string status }
  AppraisalTemplate { uuid id PK; uuid tenant_id; string name; bool is_active }
  AppraisalQuestion { uuid id PK; uuid template_id FK; string question_text; enum question_type; int order }
  Appraisal { uuid id PK; uuid tenant_id; uuid cycle_id FK; uuid employee_id FK; uuid evaluator_id; enum status; decimal overall_rating }
  AppraisalResponse { uuid id PK; uuid tenant_id; uuid appraisal_id FK; uuid question_id; string answer; decimal score }
  Goal { uuid id PK; uuid tenant_id; uuid employee_id FK; string title; string status }
  GoalProgress { uuid id PK; uuid goal_id FK; int progress; string note }
  MetricCategory { uuid id PK; uuid tenant_id; string name }
  PerformanceMetric { uuid id PK; uuid tenant_id; uuid category_id FK; string name }
  EmployeeMetric { uuid id PK; uuid tenant_id; uuid employee_id; uuid metric_id FK; decimal value }
  MetricTarget { uuid id PK; uuid tenant_id; uuid metric_id FK; decimal target }
  PerformanceReview { uuid id PK; uuid tenant_id; uuid employee_id FK; string period; string status }
  ReviewMetric { uuid id PK; uuid review_id FK; uuid metric_id; decimal score }
```

Appraisal completion → approval review routes through the approvals engine when configured.

---

## 8. Approvals engine (`approval_workflow`(+`approval_workflow_step`), `approval_request`(+`approval_step_action`))

```mermaid
erDiagram
  ApprovalWorkflow ||--o{ ApprovalWorkflowStep : steps
  ApprovalRequest ||--o{ ApprovalStepAction : actions

  ApprovalWorkflow { uuid id PK; uuid tenant_id; enum module "payroll|leave_request|contract|appraisal|performance_review|recruitment_offer|general"; string name; bool is_active }
  ApprovalWorkflowStep { uuid id PK; uuid tenant_id; uuid workflow_id FK; int sequence; string name; enum approver_type "user|role|department_head|manager|owner"; string approver_role; uuid approver_employee_id }
  ApprovalRequest { uuid id PK; uuid tenant_id; enum module; uuid object_id; uuid workflow_id; uuid requester_employee_id; enum status; int current_sequence }
  ApprovalStepAction { uuid id PK; uuid tenant_id; uuid request_id FK; int sequence; enum approver_type; string approver_role; uuid approver_employee_id; enum status "pending|approved|rejected|skipped|escalated"; uuid acted_by; text comment }
```

Typed `module` enum; tenant-scoped; manager/department_head
approvers resolve against `HRDetails`. Decomposed workflow types
(purchase_order/expense/invoice/requisition) are intentionally absent.

---

## 9. Tasks (`task`, `task_comment`, `task_log`)

```mermaid
erDiagram
  Task ||--o{ TaskComment : comments
  Task ||--o{ TaskLog : logs

  Task { uuid id PK; uuid tenant_id; string title; enum status "todo|in_progress|blocked|done|cancelled"; enum priority; uuid assignee_employee_id; int progress; date due_date }
  TaskComment { uuid id PK; uuid tenant_id; uuid task_id FK; uuid author_user_id; text body }
  TaskLog { uuid id PK; uuid tenant_id; uuid task_id FK; string action; string description }
```

ERP-internal job tracker only — **distinct** from projects-service projects/tenders.

---

## 10. Business config + reference + FX (`company_settings`, `document_sequence`, `region`, `department`, `exchange_rate`, `exchange_rate_api_settings`, `app_setting`, `api_request_metric`)

```mermaid
erDiagram
  CompanySettings { uuid id PK; uuid tenant_id UK; string legal_name; string kra_pin; string nssf_employer_no; string shif_employer_no; int financial_year_start_month; string default_currency; string timezone }
  DocumentSequence { uuid id PK; uuid tenant_id; string doc_type; string prefix; string separator; string date_format; int padding; string reset_freq; bigint current_val }
  Region { uuid id PK; uuid tenant_id "NULL=system"; string code; string name; uuid parent_region_id }
  Department { uuid id PK; uuid tenant_id; string code; string title; uuid parent_department_id }
  ExchangeRate { uuid id PK; uuid tenant_id "NULL=platform"; string base_currency; string quote_currency; decimal rate; date rate_date; string source }
  ExchangeRateAPISettings { uuid id PK; uuid tenant_id UK; string provider; string api_key_ref "secret-store env name, NOT ciphertext"; string base_currency; bool is_active }
  AppSetting { uuid id PK; uuid tenant_id; string key; string value }
  APIRequestMetric { uuid id PK; string path; int status; int duration_ms; datetime created_at }
```

`CompanySettings` has **no** branding columns (auth-api SoT), **no** tax-rate duplication
(payroll tables own those), **no** pickup/address/service-type (ordering-service).

---

## 11. Eventing + idempotency (`outbox_event`, `idempotency_key`)

```mermaid
erDiagram
  OutboxEvent { uuid id PK; uuid tenant_id; string aggregate_type; string aggregate_id; string event_type; json payload; string status "PENDING|PUBLISHED|FAILED"; datetime created_at }
  IdempotencyKey { string key PK; datetime created_at }
```

Transactional outbox drained by the shared-events `OutboxPoller`; consumers dedupe via
`IdempotencyKey`. Subjects: `erp.payroll.processed`, `erp.email.requested`,
`erp.notification.requested`, and approval lifecycle events (→ `erp.notification.requested`).
