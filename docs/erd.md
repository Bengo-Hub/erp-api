# erp-api Entity-Relationship Documentation

> Reconstructed from Django models + live `bengo_erp` schema (158 tables, PostgreSQL 17).
> Grouped by app. FKs and key fields shown. Statutory amounts use `DecimalField`.
> Django adds an implicit `id BIGSERIAL` PK unless noted (UUID PKs called out).

Cross-app FK hubs:
- `authmanagement.CustomUser` (auth user shadow) — referenced everywhere as creator/approver/owner.
- `hrm.employees.Employee` — the HR aggregate root; most HR tables FK to it.
- `business.Bussiness` — tenant/business config root (`tenant_id` → auth-api).
- `core.{Departments,Regions,Projects,BankInstitution,BankBranches}` — reference data.

---

## 1. authmanagement (identity, RBAC shadow, security, backups)

```mermaid
erDiagram
  CustomUser ||--o| UserPreferences : has
  CustomUser ||--o{ UserLog : logs
  CustomUser ||--o{ Backup : created
  CustomUser ||--o{ TwoFactorAuth : has
  CustomUser ||--o{ SecurityAuditLog : audited
  AuthTenant ||--o{ AuthOutlet : "tenant_id"

  CustomUser {
    bigint id PK
    string external_id "JWT sub (SSO), unique"
    string email UK
    string first_name
    string last_name
    string middle_name
    string phone
    image pic
    image signature "for doc approvals"
    string timezone
    datetime password_changed_at
    bool must_change_password
    bool is_active
    bool is_staff
    bool is_superuser
  }
  AuthTenant {
    uuid id PK "auth-api tenant UUID"
    string slug UK
    string name
    bool is_platform
    string status
    datetime synced_at
  }
  AuthOutlet {
    uuid id PK "auth-api outlet UUID"
    uuid tenant_id FK
    string code
    string name
    string use_case
    bool is_hq
    string status
    string timezone
  }
  PasswordPolicy { int min_length; int password_expiry_days; int max_login_attempts }
  Backup { string type; string path; bigint size; string status; string storage_type }
  BackupConfig { string storage_type; string s3_bucket; int retention_days }
  BackupSchedule { string frequency; string cron_expression; datetime next_run; bool is_active }
  UserPreferences { json theme_settings; json notification_settings; json dashboard_layout; string language }
  AccountRequest { string email; string status }
  TwoFactorAuth { string secret; bool is_enabled; json backup_codes }
  AccountLockout { int failed_attempts; datetime locked_until }
  SecurityAuditLog { string event_type; string ip_address; datetime created_at }
  SecuritySettings { bool enforce_2fa; int session_timeout }
```
> Django built-ins: `auth_group` (= ERP service roles), `auth_permission`,
> `auth_group_permissions`, `authmanagement_customuser_groups`,
> `authmanagement_customuser_user_permissions`, `authtoken_token`, `django_content_type`,
> `django_session`, `django_admin_log`, `django_site`, `django_celery_beat_*`.

---

## 2. business (tenant/business config)

```mermaid
erDiagram
  BusinessLocation ||--o{ Bussiness : location
  CustomUser ||--o{ Bussiness : owner
  Bussiness ||--o{ Branch : branches
  BusinessLocation ||--o{ Branch : location
  Bussiness ||--o| BrandingSettings : branding
  Bussiness ||--o{ TaxRates : taxrates
  Bussiness ||--o{ ProductSettings : settings
  Bussiness ||--o{ SaleSettings : settings
  Bussiness ||--o{ PrefixSettings : prefixes
  Bussiness ||--o{ ServiceTypes : services
  Bussiness ||--o{ PickupStations : stations
  Bussiness ||--o{ DocumentSequence : sequences

  Bussiness {
    bigint id PK
    uuid tenant_id UK "auth-api tenant UUID"
    string name
    date start_date
    string currency
    string finacial_year_start_month
    string stock_accounting_method
    decimal default_profit_margin
    image logo
    image business_stamp
    string kra_number "display cache; treasury is SoT"
    string business_type
    string county
    string tax_compliance_status
  }
  Branch {
    bigint id PK
    bigint business_id FK
    bigint location_id FK
    string name
    string branch_code UK
    string email
    bool is_main_branch
    bool is_active
  }
  BrandingSettings { bigint business_id FK; string primary_color_name; string surface_name; bool dark_mode }
  TaxRates { bigint business_id FK; string tax_name; string tax_number UK; decimal percentage }
  PrefixSettings { bigint business_id FK; string invoice; string quotation; string purchase_order }
  DocumentSequence { bigint business_id FK; string document_type; int current_sequence }
  PickupStations { bigint business_id FK; bigint region_id FK; string pickup_location; decimal shipping_charge }
  ServiceTypes { bigint business_id FK; string name; string packing_charge_type }
```
> `DocumentSequence` uses SELECT FOR UPDATE row locking; unique `(business, document_type)`.

---

## 3. core (reference data + settings)

```mermaid
erDiagram
  Regions ||--o{ Regions : parent
  Departments ||--o{ Departments : parent
  ProjectCategory ||--o{ Projects : projects
  BankInstitution ||--o{ BankBranches : branches
  Bussiness ||--o{ ExchangeRate : "business (null=system-wide)"
  CustomUser ||--o{ ExchangeRate : created_by

  Regions { bigint id PK; string code; string name; bigint parent_region_id FK }
  Departments { bigint id PK; string code; string title; bigint parent_departyment_id FK }
  Projects { bigint id PK; bigint category_id FK; string code; string title }
  ProjectCategory { bigint id PK; string title }
  BankInstitution { bigint id PK; string name; string code UK; string short_code UK; string swift_code }
  BankBranches { bigint id PK; bigint bank_id FK; string name; string code "uniq per bank" }
  ExchangeRate {
    bigint id PK
    string from_currency
    string to_currency
    decimal rate "18,6"
    date effective_date
    string source "manual|api|bank"
    bigint business_id FK
  }
  RegionalSettings { string timezone; string date_format; string currency_symbol "singleton pk=1" }
  AppSettings { string app_key; string cypher_key }
  Location { string name; string code UK; bigint region_id FK "LEGACY - use Branch" }
  Blog ||--o{ Post : posts
  Post ||--o{ Comments : comments
  ApiRequestMetric { string method; string path; int status_code; decimal duration_ms }
  QueryPerformanceMetric { string operation; decimal duration_ms; int query_count }
  ContractSetting { email emai_to; int duration "contract expiry notice" }
```

---

## 4. hrm.employees (HR aggregate root)

```mermaid
erDiagram
  CustomUser ||--|| Employee : user
  Bussiness ||--o{ Employee : organisation
  Employee ||--o{ SalaryDetails : salary_details
  Employee ||--o{ HRDetails : hr_details
  Employee ||--o{ Contract : contracts
  Employee ||--o{ ContactDetails : contacts
  Employee ||--o{ NextOfKin : kins
  Employee ||--o{ Documents : documents
  Employee ||--o{ EmployeeBankAccount : bank_accounts
  BankInstitution ||--o{ EmployeeBankAccount : bank
  BankBranches ||--o{ EmployeeBankAccount : branch
  EmployeeBankAccount ||--o{ SalaryDetails : bank_account
  JobTitle ||--o{ HRDetails : job_title
  Departments ||--o{ HRDetails : department
  Employee ||--o{ HRDetails : reports_to
  WorkShift ||--o{ SalaryDetails : work_shift

  Employee {
    bigint id PK
    bigint user_id FK "OneToOne"
    bigint organisation_id FK "Bussiness"
    uuid outlet_id "auth-api outlet scoping"
    string gender
    date date_of_birth
    string national_id UK
    string pin_no "KRA PIN"
    string shif_or_nhif_number
    string nssf_no
    bool deleted
    bool terminated
    bool allow_ess
    bool ess_unrestricted_access
  }
  SalaryDetails {
    bigint id PK
    bigint employee_id FK
    string employment_type
    decimal monthly_salary "14,2"
    string pay_type "basic|gross|consolidated|net_pay"
    int work_hours
    bigint work_shift_id FK
    decimal hourly_rate "auto"
    decimal daily_rate "auto"
    string income_tax "primary|secondary"
    bool deduct_shif_or_nhif
    bool deduct_nssf
    string payment_type "bank|mobile|cash|cheque"
    bigint bank_account_id FK
  }
  HRDetails {
    bigint id PK
    bigint employee_id FK
    string job_or_staff_number
    bigint job_title_id FK
    bigint department_id FK
    bigint reports_to_id FK "Employee"
    bigint branch_id FK "business.Branch"
    bigint region_id FK
    bigint project_id FK
    date date_of_employment
    bool board_director
  }
  Contract {
    bigint id PK
    bigint employee_id FK
    string contract_type
    date contract_start_date
    date contract_end_date
    string status "active|suspended|terminated|expired"
    decimal salary
    decimal contract_duration "auto days"
    date probation_end_date
  }
  EmployeeBankAccount { bigint employee_id FK; bigint bank_institution_id FK; string account_number; bool is_primary }
  ContactDetails { bigint employee_id FK; email personal_email UK; string county; string city; phone mobile_phone }
  NextOfKin { bigint employee_id FK; string name; string relation; phone phone; email email UK }
  Documents { bigint employee_id FK; file document }
  JobTitle { bigint id PK; string title }
  JobGroup { bigint id PK; string title }
  WorkersUnion { bigint id PK; string name; string code UK }
```

---

## 5. hrm.payroll_settings (payroll rules engine config)

```mermaid
erDiagram
  PayrollComponents ||--o{ Formulas : deduction
  Formulas ||--o{ FormulaItems : formulaitems
  Formulas ||--o{ SplitRatio : sliptrations
  Formulas ||--o{ Formulas : replaces_formula
  Relief ||--o{ PayrollComponents : applicable_relief
  BenefitTaxes ||--o{ PayrollComponents : applicable_tax_formula
  DefaultPayrollSettings }o--o{ PayrollComponents : "default earnings/deductions/benefits (M2M)"
  ScheduledPayslip }o--o{ Employee : recipients

  Formulas {
    bigint id PK
    string type "income|deduction|earning|fbt|levy|relief_allowance"
    bigint deduction_id FK "PayrollComponents"
    string category "primary|secondary|fbt|housing_levy|social_security_fund|nhif|shif"
    string title
    date effective_from
    date effective_to
    decimal upper_limit "14,4"
    decimal upper_limit_amount
    decimal upper_limit_percentage
    decimal personal_relief
    bool progressive
    bool is_current
    string version
    json deduction_order
  }
  FormulaItems { bigint formula_id FK; decimal amount_from; decimal amount_to; decimal deduct_amount; decimal deduct_percentage }
  SplitRatio { bigint formula_id FK; decimal employee_percentage; decimal employer_percentage }
  Relief { string type "Personal|Deductible"; string title; decimal fixed_limit; decimal percentage; bool is_active }
  PayrollComponents {
    bigint id PK
    string title
    string category "Benefits|Earnings|Deductions"
    string mode "monthly|perhour|perday|..."
    bool non_cash
    bool statutory
    bool checkoff
    string taxable_status
    string deduction_phase "before_tax|after_tax|after_paye|final"
    int deduction_priority
  }
  Loans { bigint id PK; string wb_code; string title; bool is_active }
  WithHoldingtax { string title; decimal rate; decimal threshold; date effective_from }
  BenefitTaxes { string title; money fixed_limit; decimal percentage; money min_taxable_aggregate }
  GeneralHRSettings { decimal overtime_normal_days; decimal overtime_holidays; string partial_months "singleton pk=1" }
  RepayOption { decimal amount; int no_of_installments; decimal installment_amount "auto" }
  SeverancePay { int no_of_days_per_complete_employment_year }
  ScheduledPayslip { date payroll_period; datetime scheduled_time; string status }
```

---

## 6. hrm.payroll (payroll transactions)

```mermaid
erDiagram
  Employee ||--o{ Payslip : payslips
  Payslip ||--o{ PayslipAudit : audits
  Employee ||--o{ EmployeLoans : loans
  Loans ||--o{ EmployeLoans : loan
  Employee ||--o{ Advances : advances
  Employee ||--o{ LossesAndDamages : loss_damages
  Employee ||--o{ Deductions : deductions
  Employee ||--o{ Benefits : benefits
  Employee ||--o{ Earnings : earnings
  Employee ||--o{ ExpenseClaims : expense_claims
  ExpenseClaims ||--o{ ClaimItems : items
  PayrollComponents ||--o{ Deductions : deduction
  PayrollComponents ||--o{ Benefits : benefit
  PayrollComponents ||--o{ Earnings : earning
  RepayOption ||--o{ Advances : repay_option
  CustomUser ||--o{ CustomReport : created_by

  Payslip {
    bigint id PK
    bigint employee_id FK
    bigint created_by_id FK
    decimal gross_pay
    decimal total_earnings
    decimal net_pay
    decimal taxable_pay
    decimal paye
    decimal tax_relief
    decimal shif_or_nhif_contribution
    decimal housing_levy
    decimal nssf_employee_tier_1
    decimal nssf_employee_tier_2
    decimal deductions_before_tax
    decimal deductions_after_tax
    decimal deductions_after_paye
    date payment_period
    string payroll_status "queued|processing|complete|expired"
    string approval_status "draft|pending|approved|rejected"
    bigint approver_id FK
    bool published
    string kra_paye_reference
    bool delete_status
  }
  PayslipAudit { bigint payslip_id FK; string action; bigint action_by_id FK; datetime action_date }
  EmployeLoans { bigint employee_id FK; bigint loan_id FK; decimal principal_amount; decimal amount_repaid; decimal monthly_installment; string interest_formula; date start_date; date end_date }
  Advances { bigint employee_id FK; bigint repay_option_id FK; date issue_date; date next_payment_date; decimal amount_issued; decimal amount_repaid; bool approved }
  LossesAndDamages { bigint employee_id FK; bigint repay_option_id FK; decimal damage_amount; decimal amount_repaid; bool approved }
  Deductions { bigint employee_id FK; bigint deduction_id FK; decimal amount "14,4"; decimal employer_amount; date effective_date }
  Benefits { bigint employee_id FK; bigint benefit_id FK; decimal amount; bool is_active }
  Earnings { bigint employee_id FK; bigint earning_id FK; decimal quantity; decimal rate; decimal amount }
  ExpenseClaims { bigint employee_id FK; string category; decimal amount; bool approved; bool is_paid; bool schedule_to_payroll }
  ClaimItems { bigint claim_id FK; string expense_type; decimal amount "qty*rate" }
  CustomReport { string name; string report_type "p9|p10a|statutory|..."; json params; bigint created_by_id FK }
  ExpenseCode { string code UK; string title }
  ExpenseClaimSettings { string payment_method; decimal mileage_rate_amount "singleton pk=1" }
```

---

## 7. hrm.attendance

```mermaid
erDiagram
  WorkShift ||--o{ WorkShiftSchedule : schedule
  Employee ||--o{ OffDay : off_days
  Employee ||--o{ AttendanceRecord : attendance_records
  WorkShift ||--o{ AttendanceRecord : work_shift
  WorkShift }o--o{ ShiftRotation : shifts
  Bussiness ||--o{ AttendanceRule : rules
  Employee ||--o{ Timesheet : timesheets
  Timesheet ||--o{ TimesheetEntry : entries
  ShiftRoster ||--o{ ShiftRosterSlot : slots
  ShiftRosterSlot ||--o{ ShiftAssignment : assignments
  Employee ||--o{ ShiftAssignment : assigned
  Employee ||--o{ StaffShiftOverride : overrides

  WorkShift { bigint id PK; string name; time start_time; time end_time; int grace_minutes; decimal total_hours_per_week }
  WorkShiftSchedule { bigint work_shift_id FK; string day; time start_time; time end_time; bool is_working_day }
  AttendanceRecord {
    bigint id PK
    bigint employee_id FK
    bigint work_shift_id FK
    date date
    datetime check_in
    datetime check_out
    string biometric_id
    decimal gps_latitude
    decimal gps_longitude
    string status "present|absent|late|half-day"
    int total_seconds_worked
    decimal regular_hours
    decimal overtime_hours
  }
  AttendanceRule {
    bigint id PK
    string rule_type "late|overtime|absenteeism|work_hours|break|holiday _policy"
    int priority
    decimal overtime_threshold_hours
    decimal overtime_rate_multiplier
    decimal max_overtime_hours
    decimal min_work_hours
    json public_holidays
    bigint business_id FK
    bigint branch_id FK
    bigint department_id FK
  }
  ShiftRotation { string title; bigint current_active_shift_id FK; int run_duration; string run_unit; datetime next_change_date }
  ESSSettings { bool enable_shift_based_restrictions; bool allow_payslip_view; int session_timeout_minutes "singleton pk=1" }
  Timesheet { bigint employee_id FK; date period_start; date period_end; string status; decimal total_hours; bigint approver_id FK }
  TimesheetEntry { bigint timesheet_id FK; date date; bigint project_id FK; decimal regular_hours; decimal overtime_hours }
  OffDay { bigint employee_id FK; date date; string reason }
  ShiftRoster { string name; date period_start; date period_end }
  ShiftAssignment { bigint employee_id FK; bigint slot_id FK }
  StaffShiftOverride { bigint employee_id FK; date date }
```

---

## 8. hrm.leave

```mermaid
erDiagram
  LeaveCategory ||--o{ LeaveEntitlement : entitlements
  LeaveCategory ||--o{ LeaveRequest : requests
  LeaveCategory ||--o{ LeaveBalance : balances
  Employee ||--o{ LeaveEntitlement : entitlements
  Employee ||--o{ LeaveRequest : leave_requests
  Employee ||--o{ LeaveBalance : leave_balances
  Employee ||--o{ LeaveRequest : approved_by
  LeaveRequest ||--o{ LeaveLog : logs

  LeaveCategory { bigint id PK; string name; decimal default_annual_days; bool allow_carryover; decimal max_carryover_days }
  LeaveEntitlement { bigint employee_id FK; bigint category_id FK; decimal days_entitled; int year "uniq(emp,cat,year)" }
  LeaveRequest { bigint employee_id FK; bigint category_id FK; date start_date; date end_date; decimal days_requested; string status; bigint approved_by_id FK }
  LeaveBalance { bigint employee_id FK; bigint category_id FK; int year; decimal days_entitled; decimal days_taken; decimal days_remaining }
  LeaveLog { bigint leave_request_id FK; string action; bigint user_id FK }
  PublicHoliday { bigint id PK; string name; date date; bool is_national; string county "uniq(date,county)" }
```

---

## 9. hrm.appraisals / performance / recruitment / training

```mermaid
erDiagram
  AppraisalCycle ||--o{ Appraisal : appraisals
  AppraisalTemplate ||--o{ AppraisalQuestion : questions
  AppraisalTemplate ||--o{ Appraisal : template
  Appraisal ||--o{ AppraisalResponse : responses
  AppraisalQuestion ||--o{ AppraisalResponse : question
  Employee ||--o{ Appraisal : employee
  Employee ||--o{ Goal : goals
  Goal ||--o{ GoalProgress : progress_updates

  MetricCategory ||--o{ PerformanceMetric : metrics
  PerformanceMetric ||--o{ EmployeeMetric : employee_metrics
  PerformanceMetric ||--o{ MetricTarget : targets
  Employee ||--o{ EmployeeMetric : metrics
  Employee ||--o{ PerformanceReview : reviews
  PerformanceReview ||--o{ ReviewMetric : review_metrics

  JobPosting ||--o{ Application : applications
  Candidate ||--o{ Application : applications
  TrainingCourse ||--o{ TrainingEnrollment : enrollments
  TrainingCourse ||--o{ TrainingEvaluation : evaluations
  Employee ||--o{ TrainingEnrollment : enrollments

  AppraisalCycle { string name; date start_date; date end_date; string status }
  Appraisal { bigint cycle_id FK; bigint employee_id FK; bigint evaluator_id FK; string status; decimal overall_rating "0-5" }
  Goal { bigint employee_id FK; string title; string status; int progress "0-100" }
  PerformanceMetric { bigint category_id FK; string name; string metric_type; decimal target_value }
  EmployeeMetric { bigint employee_id FK; bigint metric_id FK; text value; decimal numeric_value; date date_recorded }
  PerformanceReview { bigint employee_id FK; string title; date review_date; string status; decimal overall_rating }
  JobPosting { string title; text description; string status "draft|open|closed|archived" }
  Candidate { string full_name; email email; file resume }
  Application { bigint job_id FK; bigint candidate_id FK; string status "applied|screening|interview|offered|hired|rejected" }
  TrainingCourse { string title; date start_date; date end_date; int capacity }
  TrainingEnrollment { bigint course_id FK; bigint employee_id FK; string status "uniq(course,emp)" }
  EmployeeOnboarding { bigint employee_id FK; string status }
  OnboardingTask { bigint onboarding_id FK; string title; bool completed }
```

---

## 10. approvals (generic workflow engine)

```mermaid
erDiagram
  ApprovalWorkflow ||--o{ ApprovalStep : steps
  ApprovalWorkflow ||--o{ Approval : approvals
  ApprovalWorkflow ||--o{ ApprovalRequest : requests
  ApprovalStep ||--o{ Approval : approvals
  ApprovalStep ||--o{ ApprovalRequest : current_step
  CustomUser ||--o{ Approval : approver
  CustomUser ||--o{ ApprovalRequest : requester

  ApprovalWorkflow { bigint id PK; string name; string workflow_type "payroll|leave_request|contract|..."; bool requires_multiple_approvals; decimal approval_threshold }
  ApprovalStep { bigint workflow_id FK; int step_number; string approver_type "user|role|department_head|manager|owner"; bigint approver_user_id FK; string approver_role; bigint approver_department_id FK; bool can_delegate "uniq(workflow,step_number)" }
  Approval { int content_type_id FK; int object_id; bigint workflow_id FK; bigint step_id FK; bigint approver_id FK; bigint delegated_to_id FK; string status "pending|approved|rejected|delegated|cancelled"; decimal approval_amount }
  ApprovalRequest { int content_type_id FK; int object_id; bigint workflow_id FK; bigint requester_id FK; string status "draft|submitted|in_progress|approved|rejected|cancelled"; bigint current_step_id FK; string urgency; decimal amount; string currency }
```
> `Approval`/`ApprovalRequest` use Django **GenericForeignKey** (`content_type_id`, `object_id`)
> to attach to any model (e.g. `Payslip`). The Go port should make `module` an enum + typed
> `object_id` (UUID) like inventory-api's `ApprovalRequest`.

---

## 11. addresses

```mermaid
erDiagram
  CustomUser ||--o{ AddressBook : addresses
  PickupStations ||--o{ AddressBook : pickup_station
  AddressBook ||--o{ AddressValidation : validations
  DeliveryRegion ||--o{ PickupStations : region

  AddressBook { bigint user_id FK; string address_type; string county; string street_name; string postal_code; string delivery_type "home|pickup|office"; bigint pickup_station_id FK; bool is_default_shipping; bool is_default_billing }
  DeliveryRegion { string name; string county; decimal delivery_charge; int estimated_delivery_days; json covers_counties "uniq(name,county)" }
  AddressValidation { bigint address_id FK; string status; string validation_method; bool is_valid; decimal confidence_score }
```

---

## 12. integrations / task_management / error_handling (system)

```mermaid
erDiagram
  CustomUser ||--o{ Task : created_by
  Task ||--o{ TaskLog : logs
  CustomUser ||--o{ Error : user
  Error ||--o{ ErrorLog : logs

  EventOutbox {
    uuid id PK
    string subject "erp.{entity.action}"
    string aggregate_type
    string aggregate_id
    string tenant_id
    json payload
    string status "pending|published|failed"
    int attempts
    text error
    datetime created_at
    datetime published_at
  }
  ExchangeRateAPISettings { string provider; url api_endpoint; string access_key "ENCRYPTED"; string source_currency; json target_currencies; time fetch_time; bool is_active }
  Task { uuid id PK; string task_id UK "celery"; string task_type; string status; int progress; json input_data; json output_data }
  TaskLog { bigint task_id FK; string level; text message }
  TaskTemplate { string name UK; string task_type; json input_schema }
  Error { uuid id PK; string error_id UK; string category; string severity; string status; string module; text error_traceback }
  ErrorLog { bigint error_id FK; string level; text message }
  ErrorPattern { string name UK; text pattern "regex"; string category; bool auto_resolve }
```

---

## Table-name reference (Django `db_table` → model)

Key explicit table names (others default to `<app>_<model>`):
`employee`, `employee_salary_details`, `employee_hr_details`, `employees_contract`,
`employee_contact_details`, `employee_kin_details`, `employee_documents`,
`employee_bank_accounts`, `employee_loans`, `employee_advances`,
`employee_losses_and_damages`, `employee_deductions`, `employee_benefits`,
`employee_earnings`, `employee_expense_claims`, `payslips`, `payroll_payslipaudit`,
`jobtitles`, `job_groups`, `workers_unions`, `hrm_work_shifts`, `hrm_work_shift_schedules`,
`hrm_attendance_records`, `hrm_attendance_rules`, `hrm_off_days`, `hrm_shift_rotations`,
`hrm_public_holidays`, `ess_settings`, `business_details`, `business_branches`,
`business_location`, `business_branding_settings`, `taxrates`, `prefix_settings`,
`document_sequences`, `pickup_stations`, `service_types`, `regions`, `departments`,
`projects`, `project_categories`, `bank_institutions`, `bank_branches`, `locations`,
`address_book`, `delivery_regions`, `address_validations`, `approvals`, `approval_steps`,
`approval_workflows`, `approval_requests`, `integrations_eventoutbox`.
