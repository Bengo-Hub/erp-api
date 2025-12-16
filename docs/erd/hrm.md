# ERP Service - HRM Module Entity Relationship Diagram

The HRM module manages employees, payroll, attendance, leave, recruitment, training, and performance management.

> **Conventions**
> - UUID primary keys (Django uses auto-incrementing integers by default, but can be configured for UUIDs).
> - `tenant_id` (via `organisation_id`) on all operational tables for multi-tenant isolation.
> - Timestamps are `TIMESTAMPTZ` with timezone awareness.
> - Monetary values use `DECIMAL(14,2)` or `DECIMAL(15,2)` with decimal precision.
> - All tables include `created_at` and `updated_at` timestamps.
> - Soft deletes via `deleted` or `is_deleted` boolean flag where applicable.

---

## Employee Management

### employees

**Purpose**: Employee profiles and basic information.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Employee identifier |
| `user_id` | INTEGER | FK → auth_users(id), UNIQUE | User reference (from auth-service) |
| `organisation_id` | INTEGER | FK → businesses(id) | Business/tenant reference |
| `gender` | VARCHAR(10) | CHECK | male, female, other |
| `passport_photo` | VARCHAR(255) | | Photo file path |
| `date_of_birth` | DATE | | Date of birth |
| `residential_status` | VARCHAR(50) | CHECK | Resident, Non-Resident |
| `national_id` | VARCHAR(20) | UNIQUE | National ID number |
| `pin_no` | VARCHAR(16) | | KRA PIN number |
| `shif_or_nhif_number` | VARCHAR(16) | | SHIF/NHIF number |
| `nssf_no` | VARCHAR(16) | | NSSF number |
| `deleted` | BOOLEAN | DEFAULT false | Soft delete flag |
| `terminated` | BOOLEAN | DEFAULT false | Termination flag |
| `allow_ess` | BOOLEAN | DEFAULT false | Employee Self-Service access |
| `ess_activated_at` | TIMESTAMPTZ | | ESS activation date |
| `ess_last_login` | TIMESTAMPTZ | | ESS last login |
| `ess_unrestricted_access` | BOOLEAN | DEFAULT false | Unrestricted ESS access |

**Indexes**:
- `idx_employee_user` ON `user_id`
- `idx_employee_organisation` ON `organisation_id`
- `idx_employee_national_id` ON `national_id`
- `idx_employee_deleted` ON `deleted`
- `idx_employee_terminated` ON `terminated`

**Relations**:
- `user_id` → `auth_users(id)` (references auth-service, OneToOne)
- `organisation_id` → `businesses(id)` (tenant reference)

**Related Models** (via foreign keys):
- `hr_details` - HR details (department, position, etc.)
- `salary_details` - Salary information
- `employee_bank_accounts` - Bank account details

### employee_bank_accounts

**Purpose**: Employee bank account information for payroll.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Bank account identifier |
| `employee_id` | INTEGER | FK → employees(id) | Employee reference |
| `bank_institution_id` | INTEGER | FK → bank_institutions(id) | Bank reference |
| `bank_branch_id` | INTEGER | FK → bank_branches(id) | Bank branch reference |
| `account_number` | VARCHAR(50) | | Account number |
| `account_name` | VARCHAR(255) | | Account name |
| `is_primary` | BOOLEAN | DEFAULT false | Primary account flag |

**Indexes**:
- `idx_employee_bank_account_employee` ON `employee_id`
- `idx_employee_bank_account_bank` ON `bank_institution_id`

**Relations**:
- `employee_id` → `employees(id)`

---

## Payroll Management

### payroll_records

**Purpose**: Payroll processing records for each pay period.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Payroll record identifier |
| `employee_id` | INTEGER | FK → employees(id) | Employee reference |
| `pay_period` | VARCHAR(20) | | Pay period (e.g., "2024-12") |
| `pay_date` | DATE | | Pay date |
| `gross_salary` | DECIMAL(14,2) | DEFAULT 0.00 | Gross salary |
| `allowances` | DECIMAL(14,2) | DEFAULT 0.00 | Total allowances |
| `deductions` | DECIMAL(14,2) | DEFAULT 0.00 | Total deductions |
| `net_salary` | DECIMAL(14,2) | DEFAULT 0.00 | Net salary |
| `tax_amount` | DECIMAL(14,2) | DEFAULT 0.00 | Tax amount |
| `status` | VARCHAR(20) | CHECK | draft, processed, paid, cancelled |
| `processed_at` | TIMESTAMPTZ | | Processing timestamp |
| `processed_by_id` | INTEGER | FK → auth_users(id) | Processor (references auth-service) |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_payroll_record_employee` ON `employee_id`
- `idx_payroll_record_pay_period` ON `pay_period`
- `idx_payroll_record_pay_date` ON `pay_date`
- `idx_payroll_record_status` ON `status`

**Relations**:
- `employee_id` → `employees(id)`
- `processed_by_id` → `auth_users(id)` (references auth-service)

**Integration Points**:
- When payroll is processed → Publish `erp.payroll.processed` event → treasury-app creates payments

### employee_loans

**Purpose**: Employee loan tracking and repayment.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Loan record identifier |
| `employee_id` | INTEGER | FK → employees(id) | Employee reference |
| `loan_id` | INTEGER | FK → loans(id) | Loan type reference |
| `principal_amount` | DECIMAL(14,4) | DEFAULT 0.00 | Principal amount |
| `amount_repaid` | DECIMAL(14,4) | DEFAULT 0.00 | Amount repaid |
| `interest_paid` | DECIMAL(14,4) | DEFAULT 0.00 | Interest paid |
| `no_of_installments_paid` | INTEGER | DEFAULT 0 | Installments paid |
| `monthly_installment` | DECIMAL(14,4) | DEFAULT 0.00 | Monthly installment |
| `interest_rate` | DECIMAL(10,2) | DEFAULT 0.00 | Interest rate |
| `interest_formula` | VARCHAR(100) | CHECK | Reducing Balance, Fixed |
| `fringe_benefit_tax_id` | INTEGER | FK → formulas(id) | FBT formula reference |
| `is_active` | BOOLEAN | DEFAULT false | Active loan flag |
| `start_date` | DATE | | Loan start date |
| `end_date` | DATE | | Loan end date |

**Indexes**:
- `idx_employee_loan_employee` ON `employee_id`
- `idx_employee_loan_loan` ON `loan_id`
- `idx_employee_loan_active` ON `is_active`

**Relations**:
- `employee_id` → `employees(id)`
- `loan_id` → `loans(id)` (from payroll_settings)

### advances

**Purpose**: Employee advance payments.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Advance identifier |
| `employee_id` | INTEGER | FK → employees(id) | Employee reference |
| `approver_id` | INTEGER | FK → auth_users(id) | Approver (references auth-service) |
| `approved` | BOOLEAN | DEFAULT false | Approval status |
| `issue_date` | DATE | | Issue date |
| `repay_option_id` | INTEGER | FK → repay_options(id) | Repayment option |
| `prev_payment_date` | DATE | | Previous payment date |
| `next_payment_date` | DATE | | Next payment date |
| `amount` | DECIMAL(14,2) | DEFAULT 0.00 | Advance amount |
| `amount_repaid` | DECIMAL(14,2) | DEFAULT 0.00 | Amount repaid |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

**Indexes**:
- `idx_advance_employee` ON `employee_id`
- `idx_advance_approved` ON `approved`
- `idx_advance_issue_date` ON `issue_date`

**Relations**:
- `employee_id` → `employees(id)`
- `approver_id` → `auth_users(id)` (references auth-service)
- `repay_option_id` → `repay_options(id)` (from payroll_settings)

---

## Attendance Management

### hrm_work_shifts

**Purpose**: Work shift definitions.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Shift identifier |
| `name` | VARCHAR(100) | NOT NULL | Shift name |
| `start_time` | TIME | | Default start time (legacy) |
| `end_time` | TIME | | Default end time (legacy) |
| `grace_minutes` | INTEGER | DEFAULT 0 | Grace period (minutes) |
| `total_hours_per_week` | DECIMAL(5,2) | DEFAULT 40.00 | Total hours per week |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_work_shift_name` ON `name`
- `idx_work_shift_created_at` ON `created_at`

### hrm_work_shift_schedules

**Purpose**: Day-wise schedule for work shifts.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Schedule identifier |
| `work_shift_id` | INTEGER | FK → hrm_work_shifts(id) | Shift reference |
| `day` | VARCHAR(10) | CHECK | Monday-Sunday |
| `start_time` | TIME | | Start time for this day |
| `end_time` | TIME | | End time for this day |
| `break_hours` | DECIMAL(3,1) | DEFAULT 0.0 | Break hours |
| `is_working_day` | BOOLEAN | DEFAULT true | Working day flag |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_shift_schedule_shift_day` ON `work_shift_id`, `day` (UNIQUE)
- `idx_shift_schedule_day` ON `day`
- `idx_shift_schedule_working` ON `is_working_day`

**Relations**:
- `work_shift_id` → `hrm_work_shifts(id)`

### hrm_attendance_records

**Purpose**: Employee attendance tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Attendance record identifier |
| `employee_id` | INTEGER | FK → employees(id) | Employee reference |
| `date` | DATE | NOT NULL | Attendance date |
| `check_in_time` | TIMESTAMPTZ | | Check-in timestamp |
| `check_out_time` | TIMESTAMPTZ | | Check-out timestamp |
| `hours_worked` | DECIMAL(5,2) | | Hours worked |
| `status` | VARCHAR(20) | CHECK | present, absent, late, early_leave, half_day |
| `shift_id` | INTEGER | FK → hrm_work_shifts(id) | Shift reference |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_attendance_record_employee` ON `employee_id`
- `idx_attendance_record_date` ON `date`
- `idx_attendance_record_status` ON `status`
- `idx_attendance_record_shift` ON `shift_id`

**Relations**:
- `employee_id` → `employees(id)`
- `shift_id` → `hrm_work_shifts(id)`

### hrm_off_days

**Purpose**: Employee off days (holidays, personal days).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Off day identifier |
| `employee_id` | INTEGER | FK → employees(id) | Employee reference |
| `date` | DATE | NOT NULL | Off day date |
| `reason` | VARCHAR(255) | | Reason |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

**Indexes**:
- `idx_off_day_employee` ON `employee_id`
- `idx_off_day_date` ON `date`

**Relations**:
- `employee_id` → `employees(id)`

---

## Leave Management

### leave_categories

**Purpose**: Leave type definitions.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Category identifier |
| `name` | VARCHAR(100) | NOT NULL | Category name |
| `description` | TEXT | | Description |
| `is_active` | BOOLEAN | DEFAULT true | Active flag |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_leave_category_name` ON `name`
- `idx_leave_category_active` ON `is_active`

### leave_entitlements

**Purpose**: Employee leave entitlements per year.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Entitlement identifier |
| `employee_id` | INTEGER | FK → employees(id) | Employee reference |
| `category_id` | INTEGER | FK → leave_categories(id) | Category reference |
| `days_entitled` | DECIMAL(5,2) | | Days entitled |
| `year` | INTEGER | NOT NULL | Year |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_leave_entitlement_employee` ON `employee_id`
- `idx_leave_entitlement_category` ON `category_id`
- `idx_leave_entitlement_year` ON `year`
- UNIQUE(`employee_id`, `category_id`, `year`)

**Relations**:
- `employee_id` → `employees(id)`
- `category_id` → `leave_categories(id)`

### leave_requests

**Purpose**: Employee leave requests.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Leave request identifier |
| `employee_id` | INTEGER | FK → employees(id) | Employee reference |
| `category_id` | INTEGER | FK → leave_categories(id) | Category reference |
| `start_date` | DATE | NOT NULL | Start date |
| `end_date` | DATE | NOT NULL | End date |
| `days_requested` | DECIMAL(5,2) | | Days requested |
| `reason` | TEXT | | Reason |
| `status` | VARCHAR(20) | CHECK | pending, approved, rejected, cancelled |
| `approved_by_id` | INTEGER | FK → auth_users(id) | Approver (references auth-service) |
| `approved_at` | TIMESTAMPTZ | | Approval timestamp |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Indexes**:
- `idx_leave_request_employee` ON `employee_id`
- `idx_leave_request_category` ON `category_id`
- `idx_leave_request_status` ON `status`
- `idx_leave_request_start_date` ON `start_date`
- `idx_leave_request_end_date` ON `end_date`

**Relations**:
- `employee_id` → `employees(id)`
- `category_id` → `leave_categories(id)`
- `approved_by_id` → `auth_users(id)` (references auth-service)

**Integration Points**:
- When leave is requested → Publish `erp.leave.requested` event → notifications-service sends notification

---

## Recruitment

### hrm_recruitment_job_postings

**Purpose**: Job posting management.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Job posting identifier |
| `title` | VARCHAR(255) | NOT NULL | Job title |
| `description` | TEXT | | Job description |
| `department` | VARCHAR(255) | | Department |
| `location` | VARCHAR(255) | | Location |
| `status` | VARCHAR(20) | CHECK | draft, open, closed, archived |
| `posted_at` | TIMESTAMPTZ | DEFAULT NOW() | Posted timestamp |
| `closed_at` | TIMESTAMPTZ | | Closed timestamp |

**Indexes**:
- `idx_job_posting_status` ON `status`
- `idx_job_posting_posted_at` ON `posted_at`

### hrm_recruitment_candidates

**Purpose**: Candidate information.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Candidate identifier |
| `full_name` | VARCHAR(255) | NOT NULL | Full name |
| `email` | VARCHAR(255) | NOT NULL | Email address |
| `phone` | VARCHAR(50) | | Phone number |
| `resume` | VARCHAR(255) | | Resume file path |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |

**Indexes**:
- `idx_candidate_email` ON `email`
- `idx_candidate_created_at` ON `created_at`

### hrm_recruitment_applications

**Purpose**: Job applications.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Application identifier |
| `job_posting_id` | INTEGER | FK → hrm_recruitment_job_postings(id) | Job posting reference |
| `candidate_id` | INTEGER | FK → hrm_recruitment_candidates(id) | Candidate reference |
| `status` | VARCHAR(20) | CHECK | applied, screening, interview, offered, hired, rejected |
| `applied_at` | TIMESTAMPTZ | DEFAULT NOW() | Applied timestamp |
| `interview_date` | TIMESTAMPTZ | | Interview date |
| `offer_date` | TIMESTAMPTZ | | Offer date |
| `hired_at` | TIMESTAMPTZ | | Hired timestamp |

**Indexes**:
- `idx_application_job_posting` ON `job_posting_id`
- `idx_application_candidate` ON `candidate_id`
- `idx_application_status` ON `status`
- `idx_application_applied_at` ON `applied_at`

**Relations**:
- `job_posting_id` → `hrm_recruitment_job_postings(id)`
- `candidate_id` → `hrm_recruitment_candidates(id)`

---

## Integration Points

### External Service References

**Auth Service**:
- `employees.user_id` → `auth_users(id)` (OneToOne, user identity)
- `payroll_records.processed_by_id` → `auth_users(id)` (processor)
- `leave_requests.approved_by_id` → `auth_users(id)` (approver)
- `advances.approver_id` → `auth_users(id)` (approver)

**Treasury Service**:
- When `payroll_records.status` = "processed" → Publish `erp.payroll.processed` event → treasury-app creates payments
- Employee expenses → Publish `erp.expense.approved` event → treasury-app records expense

**Notifications Service**:
- Payroll notifications → Publish `erp.payroll.processed` event
- Leave approval notifications → Publish `erp.leave.requested` event

---

## Views & Functions

### Recommended Views

**v_hrm_employee_summary**:
- Employee details with payroll, attendance, and leave summary

**v_hrm_payroll_summary**:
- Payroll totals by period
- Tax summaries

**v_hrm_attendance_summary**:
- Attendance statistics by employee, department, period

**v_hrm_leave_balance**:
- Leave balances by employee and category

---

## Maintenance Notes

- Maintain this document alongside Django model changes.
- After changing Django models, run migrations and refresh the ERD.
- Financial transactions (payroll payments) are managed by treasury-app - do not duplicate financial logic.
- User management is handled by auth-service - reference user IDs only.

