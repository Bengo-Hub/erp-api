-- Create "payslips" table
CREATE TABLE "payslips" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "outlet_id" uuid NULL, "employee_id" uuid NOT NULL, "created_by" uuid NULL, "approver_id" uuid NULL, "gross_pay" numeric(18,4) NOT NULL, "total_earnings" numeric(18,4) NOT NULL, "net_pay" numeric(18,4) NOT NULL, "taxable_pay" numeric(18,4) NOT NULL, "paye" numeric(18,4) NOT NULL, "tax_relief" numeric(18,4) NOT NULL, "reliefs" numeric(18,4) NOT NULL, "gross_pay_after_tax" numeric(18,4) NOT NULL, "shif_or_nhif_contribution" numeric(18,4) NOT NULL, "housing_levy" numeric(18,4) NOT NULL, "nssf_employee_tier_1" numeric(18,4) NOT NULL, "nssf_employee_tier_2" numeric(18,4) NOT NULL, "nssf_employer_contribution" numeric(18,4) NOT NULL, "deductions_before_tax" numeric(18,4) NOT NULL, "deductions_after_tax" numeric(18,4) NOT NULL, "deductions_after_paye" numeric(18,4) NOT NULL, "deductions_final" numeric(18,4) NOT NULL, "payment_period" timestamptz NULL, "period_start" timestamptz NULL, "period_end" timestamptz NULL, "payroll_status" character varying NOT NULL DEFAULT 'queued', "approval_status" character varying NOT NULL DEFAULT 'draft', "published" boolean NOT NULL DEFAULT false, "batch_ref" character varying NULL, "kra_paye_reference" character varying NULL, "kra_filed_at" timestamptz NULL, "delete_status" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "payslip_batch_ref" to table: "payslips"
CREATE INDEX "payslip_batch_ref" ON "payslips" ("batch_ref");
-- Create index "payslip_employee_id" to table: "payslips"
CREATE INDEX "payslip_employee_id" ON "payslips" ("employee_id");
-- Create index "payslip_tenant_id" to table: "payslips"
CREATE INDEX "payslip_tenant_id" ON "payslips" ("tenant_id");
-- Create index "payslip_tenant_id_outlet_id_payment_period" to table: "payslips"
CREATE INDEX "payslip_tenant_id_outlet_id_payment_period" ON "payslips" ("tenant_id", "outlet_id", "payment_period");
-- Create index "payslip_tenant_id_payment_period" to table: "payslips"
CREATE INDEX "payslip_tenant_id_payment_period" ON "payslips" ("tenant_id", "payment_period");
-- Create "employee_benefits" table
CREATE TABLE "employee_benefits" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "component_id" uuid NULL, "amount" numeric(18,4) NOT NULL, "non_cash" boolean NOT NULL DEFAULT false, "is_active" boolean NOT NULL DEFAULT true, "effective_date" timestamptz NULL, "end_date" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "employeebenefit_employee_id" to table: "employee_benefits"
CREATE INDEX "employeebenefit_employee_id" ON "employee_benefits" ("employee_id");
-- Create index "employeebenefit_employee_id_is_active" to table: "employee_benefits"
CREATE INDEX "employeebenefit_employee_id_is_active" ON "employee_benefits" ("employee_id", "is_active");
-- Create index "employeebenefit_tenant_id" to table: "employee_benefits"
CREATE INDEX "employeebenefit_tenant_id" ON "employee_benefits" ("tenant_id");
-- Create "app_settings" table
CREATE TABLE "app_settings" ("id" uuid NOT NULL, "tenant_id" uuid NULL, "app_key" character varying NOT NULL, "value" text NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "appsetting_app_key" to table: "app_settings"
CREATE INDEX "appsetting_app_key" ON "app_settings" ("app_key");
-- Create index "appsetting_tenant_id_app_key" to table: "app_settings"
CREATE UNIQUE INDEX "appsetting_tenant_id_app_key" ON "app_settings" ("tenant_id", "app_key");
-- Create "workers_unions" table
CREATE TABLE "workers_unions" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "name" character varying NOT NULL, "code" character varying NOT NULL, "registration_number" character varying NULL, "contact_person" character varying NULL, "contact_email" character varying NULL, "contact_phone" character varying NULL, "description" text NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "workersunion_tenant_id" to table: "workers_unions"
CREATE INDEX "workersunion_tenant_id" ON "workers_unions" ("tenant_id");
-- Create index "workersunion_tenant_id_code" to table: "workers_unions"
CREATE UNIQUE INDEX "workersunion_tenant_id_code" ON "workers_unions" ("tenant_id", "code");
-- Create "auth_tenants" table
CREATE TABLE "auth_tenants" ("id" uuid NOT NULL, "slug" character varying NOT NULL, "name" character varying NOT NULL, "is_platform" boolean NOT NULL DEFAULT false, "status" character varying NOT NULL DEFAULT 'active', "synced_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "auth_tenants_slug_key" to table: "auth_tenants"
CREATE UNIQUE INDEX "auth_tenants_slug_key" ON "auth_tenants" ("slug");
-- Create index "authtenant_slug" to table: "auth_tenants"
CREATE UNIQUE INDEX "authtenant_slug" ON "auth_tenants" ("slug");
-- Create index "authtenant_status" to table: "auth_tenants"
CREATE INDEX "authtenant_status" ON "auth_tenants" ("status");
-- Create "with_holding_taxes" table
CREATE TABLE "with_holding_taxes" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "title" character varying NOT NULL DEFAULT 'Default Tax', "rate" numeric(10,4) NOT NULL, "threshold" numeric(18,4) NOT NULL, "is_active" boolean NOT NULL DEFAULT true, "effective_from" timestamptz NULL, "effective_to" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "withholdingtax_tenant_id" to table: "with_holding_taxes"
CREATE INDEX "withholdingtax_tenant_id" ON "with_holding_taxes" ("tenant_id");
-- Create index "withholdingtax_tenant_id_is_active" to table: "with_holding_taxes"
CREATE INDEX "withholdingtax_tenant_id_is_active" ON "with_holding_taxes" ("tenant_id", "is_active");
-- Create "salary_details" table
CREATE TABLE "salary_details" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "monthly_salary" numeric(18,4) NOT NULL, "pay_mode" character varying NULL, "income_tax" character varying NOT NULL DEFAULT 'primary', "currency" character varying NOT NULL DEFAULT 'KES', "hourly_rate" numeric(18,4) NOT NULL, "daily_rate" numeric(18,4) NOT NULL, "bank_account_id" uuid NULL, "job_group_id" uuid NULL, "workers_union_id" uuid NULL, "is_active" boolean NOT NULL DEFAULT true, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "salarydetails_employee_id" to table: "salary_details"
CREATE INDEX "salarydetails_employee_id" ON "salary_details" ("employee_id");
-- Create index "salarydetails_tenant_id" to table: "salary_details"
CREATE INDEX "salarydetails_tenant_id" ON "salary_details" ("tenant_id");
-- Create "benefit_taxes" table
CREATE TABLE "benefit_taxes" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "title" character varying NOT NULL, "actual_amount" boolean NOT NULL DEFAULT true, "fixed_limit" numeric(18,4) NOT NULL, "percentage" numeric(10,4) NOT NULL, "percent_of" character varying NULL, "amounts_greater_than" numeric(18,4) NOT NULL, "min_taxable_aggregate" numeric(18,4) NOT NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "benefittax_tenant_id" to table: "benefit_taxes"
CREATE INDEX "benefittax_tenant_id" ON "benefit_taxes" ("tenant_id");
-- Create "claim_items" table
CREATE TABLE "claim_items" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "expense_claim_id" uuid NOT NULL, "expense_type" character varying NULL, "description" character varying NULL, "amount" numeric(18,4) NOT NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "claimitem_expense_claim_id" to table: "claim_items"
CREATE INDEX "claimitem_expense_claim_id" ON "claim_items" ("expense_claim_id");
-- Create index "claimitem_tenant_id" to table: "claim_items"
CREATE INDEX "claimitem_tenant_id" ON "claim_items" ("tenant_id");
-- Create "contact_details" table
CREATE TABLE "contact_details" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "personal_email" character varying NULL, "phone" character varying NULL, "alternate_phone" character varying NULL, "postal_address" character varying NULL, "physical_address" character varying NULL, "city" character varying NULL, "country" character varying NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "contactdetails_employee_id" to table: "contact_details"
CREATE INDEX "contactdetails_employee_id" ON "contact_details" ("employee_id");
-- Create index "contactdetails_tenant_id" to table: "contact_details"
CREATE INDEX "contactdetails_tenant_id" ON "contact_details" ("tenant_id");
-- Create "contracts" table
CREATE TABLE "contracts" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "contract_type" character varying NULL, "start_date" timestamptz NULL, "end_date" timestamptz NULL, "duration_months" bigint NULL, "salary" numeric(18,4) NOT NULL, "status" character varying NOT NULL DEFAULT 'active', "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "contract_employee_id" to table: "contracts"
CREATE INDEX "contract_employee_id" ON "contracts" ("employee_id");
-- Create index "contract_tenant_id" to table: "contracts"
CREATE INDEX "contract_tenant_id" ON "contracts" ("tenant_id");
-- Create "repay_options" table
CREATE TABLE "repay_options" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "amount" numeric(18,4) NOT NULL, "no_of_installments" bigint NOT NULL DEFAULT 1, "installment_amount" numeric(18,4) NOT NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "repayoption_tenant_id" to table: "repay_options"
CREATE INDEX "repayoption_tenant_id" ON "repay_options" ("tenant_id");
-- Create "departments" table
CREATE TABLE "departments" ("id" uuid NOT NULL, "tenant_id" uuid NULL, "code" character varying NULL, "title" character varying NOT NULL, "parent_department_id" uuid NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "department_code" to table: "departments"
CREATE INDEX "department_code" ON "departments" ("code");
-- Create index "department_tenant_id" to table: "departments"
CREATE INDEX "department_tenant_id" ON "departments" ("tenant_id");
-- Create "loan_types" table
CREATE TABLE "loan_types" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "wb_code" character varying NULL, "account_code" character varying NULL, "title" character varying NOT NULL, "is_active" boolean NOT NULL DEFAULT false, "round_off" numeric(10,4) NOT NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "loantype_tenant_id" to table: "loan_types"
CREATE INDEX "loantype_tenant_id" ON "loan_types" ("tenant_id");
-- Create "employee_bank_accounts" table
CREATE TABLE "employee_bank_accounts" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "bank_institution_id" uuid NULL, "bank_branch_id" uuid NULL, "account_name" character varying NOT NULL, "account_number" character varying NOT NULL, "account_type" character varying NOT NULL DEFAULT 'savings', "is_primary" boolean NOT NULL DEFAULT false, "status" character varying NOT NULL DEFAULT 'active', "is_verified" boolean NOT NULL DEFAULT false, "opened_date" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "employeebankaccount_employee_id" to table: "employee_bank_accounts"
CREATE INDEX "employeebankaccount_employee_id" ON "employee_bank_accounts" ("employee_id");
-- Create index "employeebankaccount_employee_id_is_primary" to table: "employee_bank_accounts"
CREATE INDEX "employeebankaccount_employee_id_is_primary" ON "employee_bank_accounts" ("employee_id", "is_primary");
-- Create index "employeebankaccount_tenant_id" to table: "employee_bank_accounts"
CREATE INDEX "employeebankaccount_tenant_id" ON "employee_bank_accounts" ("tenant_id");
-- Create "job_titles" table
CREATE TABLE "job_titles" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "title" character varying NOT NULL, "description" text NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "jobtitle_tenant_id" to table: "job_titles"
CREATE INDEX "jobtitle_tenant_id" ON "job_titles" ("tenant_id");
-- Create index "jobtitle_tenant_id_title" to table: "job_titles"
CREATE INDEX "jobtitle_tenant_id_title" ON "job_titles" ("tenant_id", "title");
-- Create "employee_documents" table
CREATE TABLE "employee_documents" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "title" character varying NOT NULL, "document_type" character varying NULL, "file_url" character varying NULL, "expiry_date" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "employeedocument_employee_id" to table: "employee_documents"
CREATE INDEX "employeedocument_employee_id" ON "employee_documents" ("employee_id");
-- Create index "employeedocument_tenant_id" to table: "employee_documents"
CREATE INDEX "employeedocument_tenant_id" ON "employee_documents" ("tenant_id");
-- Create "employee_loans" table
CREATE TABLE "employee_loans" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "loan_type_id" uuid NULL, "principal_amount" numeric(18,4) NOT NULL, "amount_repaid" numeric(18,4) NOT NULL, "interest_paid" numeric(18,4) NOT NULL, "no_of_installments_paid" bigint NOT NULL DEFAULT 0, "monthly_installment" numeric(18,4) NOT NULL, "interest_rate" numeric(10,4) NOT NULL, "interest_formula" character varying NULL, "is_active" boolean NOT NULL DEFAULT false, "start_date" timestamptz NULL, "end_date" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "employeeloan_employee_id" to table: "employee_loans"
CREATE INDEX "employeeloan_employee_id" ON "employee_loans" ("employee_id");
-- Create index "employeeloan_employee_id_is_active" to table: "employee_loans"
CREATE INDEX "employeeloan_employee_id_is_active" ON "employee_loans" ("employee_id", "is_active");
-- Create index "employeeloan_tenant_id" to table: "employee_loans"
CREATE INDEX "employeeloan_tenant_id" ON "employee_loans" ("tenant_id");
-- Create "expense_claims" table
CREATE TABLE "expense_claims" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "approver_id" uuid NULL, "approved" boolean NOT NULL DEFAULT false, "category" character varying NULL, "application_date" timestamptz NULL, "payment_date" timestamptz NULL, "attachment_url" character varying NULL, "amount" numeric(18,4) NOT NULL, "is_active" boolean NOT NULL DEFAULT true, "is_paid" boolean NOT NULL DEFAULT false, "schedule_to_payroll" boolean NOT NULL DEFAULT false, "delete_status" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "expenseclaim_employee_id" to table: "expense_claims"
CREATE INDEX "expenseclaim_employee_id" ON "expense_claims" ("employee_id");
-- Create index "expenseclaim_tenant_id" to table: "expense_claims"
CREATE INDEX "expenseclaim_tenant_id" ON "expense_claims" ("tenant_id");
-- Create "general_hr_settings" table
CREATE TABLE "general_hr_settings" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "overtime_normal_days" numeric(10,4) NOT NULL, "overtime_non_working_days" numeric(10,4) NOT NULL, "overtime_holidays" numeric(10,4) NOT NULL, "partial_months" character varying NOT NULL DEFAULT 'prorate_calendar', "round_off_currency" character varying NOT NULL DEFAULT 'KES', "round_off_amount" numeric(18,4) NOT NULL, "allow_backwards_payroll" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "general_hr_settings_tenant_id_key" to table: "general_hr_settings"
CREATE UNIQUE INDEX "general_hr_settings_tenant_id_key" ON "general_hr_settings" ("tenant_id");
-- Create index "generalhrsettings_tenant_id" to table: "general_hr_settings"
CREATE UNIQUE INDEX "generalhrsettings_tenant_id" ON "general_hr_settings" ("tenant_id");
-- Create "hr_details" table
CREATE TABLE "hr_details" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "job_title_id" uuid NULL, "department_id" uuid NULL, "head_of_department_id" uuid NULL, "reports_to_id" uuid NULL, "region_id" uuid NULL, "project_id" uuid NULL, "employment_type" character varying NULL, "date_joined" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "hrdetails_employee_id" to table: "hr_details"
CREATE INDEX "hrdetails_employee_id" ON "hr_details" ("employee_id");
-- Create index "hrdetails_tenant_id" to table: "hr_details"
CREATE INDEX "hrdetails_tenant_id" ON "hr_details" ("tenant_id");
-- Create "idempotency_keys" table
CREATE TABLE "idempotency_keys" ("id" uuid NOT NULL, "key" character varying NOT NULL, "scope" character varying NOT NULL DEFAULT 'default', "tenant_id" uuid NULL, "status" character varying NOT NULL DEFAULT 'processed', "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "idempotency_keys_key_key" to table: "idempotency_keys"
CREATE UNIQUE INDEX "idempotency_keys_key_key" ON "idempotency_keys" ("key");
-- Create index "idempotencykey_created_at" to table: "idempotency_keys"
CREATE INDEX "idempotencykey_created_at" ON "idempotency_keys" ("created_at");
-- Create index "idempotencykey_key" to table: "idempotency_keys"
CREATE UNIQUE INDEX "idempotencykey_key" ON "idempotency_keys" ("key");
-- Create index "idempotencykey_scope" to table: "idempotency_keys"
CREATE INDEX "idempotencykey_scope" ON "idempotency_keys" ("scope");
-- Create "api_request_metrics" table
CREATE TABLE "api_request_metrics" ("id" uuid NOT NULL, "tenant_id" uuid NULL, "method" character varying NOT NULL, "path" character varying NOT NULL, "status_code" bigint NOT NULL, "duration_ms" double precision NOT NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "apirequestmetric_created_at" to table: "api_request_metrics"
CREATE INDEX "apirequestmetric_created_at" ON "api_request_metrics" ("created_at");
-- Create index "apirequestmetric_path" to table: "api_request_metrics"
CREATE INDEX "apirequestmetric_path" ON "api_request_metrics" ("path");
-- Create index "apirequestmetric_status_code" to table: "api_request_metrics"
CREATE INDEX "apirequestmetric_status_code" ON "api_request_metrics" ("status_code");
-- Create "job_groups" table
CREATE TABLE "job_groups" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "title" character varying NOT NULL, "description" text NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "jobgroup_tenant_id" to table: "job_groups"
CREATE INDEX "jobgroup_tenant_id" ON "job_groups" ("tenant_id");
-- Create index "jobgroup_tenant_id_title" to table: "job_groups"
CREATE INDEX "jobgroup_tenant_id_title" ON "job_groups" ("tenant_id", "title");
-- Create "employees" table
CREATE TABLE "employees" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "outlet_id" uuid NULL, "user_id" uuid NULL, "employee_number" character varying NULL, "first_name" character varying NULL, "last_name" character varying NULL, "email" character varying NULL, "gender" character varying NULL, "date_of_birth" timestamptz NULL, "residential_status" character varying NULL, "national_id" character varying NULL, "pin_no" character varying NULL, "shif_or_nhif_number" character varying NULL, "nssf_no" character varying NULL, "terminated" boolean NOT NULL DEFAULT false, "deleted" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "employee_tenant_id" to table: "employees"
CREATE INDEX "employee_tenant_id" ON "employees" ("tenant_id");
-- Create index "employee_tenant_id_deleted" to table: "employees"
CREATE INDEX "employee_tenant_id_deleted" ON "employees" ("tenant_id", "deleted");
-- Create index "employee_tenant_id_national_id" to table: "employees"
CREATE UNIQUE INDEX "employee_tenant_id_national_id" ON "employees" ("tenant_id", "national_id");
-- Create index "employee_tenant_id_outlet_id" to table: "employees"
CREATE INDEX "employee_tenant_id_outlet_id" ON "employees" ("tenant_id", "outlet_id");
-- Create index "employee_user_id" to table: "employees"
CREATE INDEX "employee_user_id" ON "employees" ("user_id");
-- Create "loss_and_damages" table
CREATE TABLE "loss_and_damages" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "approver_id" uuid NULL, "repay_option_id" uuid NULL, "description" character varying NULL, "approved" boolean NOT NULL DEFAULT false, "issue_date" timestamptz NULL, "prev_payment_date" timestamptz NULL, "next_payment_date" timestamptz NULL, "damage_amount" numeric(18,4) NOT NULL, "amount_repaid" numeric(18,4) NOT NULL, "is_active" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "lossanddamage_employee_id" to table: "loss_and_damages"
CREATE INDEX "lossanddamage_employee_id" ON "loss_and_damages" ("employee_id");
-- Create index "lossanddamage_employee_id_is_active" to table: "loss_and_damages"
CREATE INDEX "lossanddamage_employee_id_is_active" ON "loss_and_damages" ("employee_id", "is_active");
-- Create index "lossanddamage_tenant_id" to table: "loss_and_damages"
CREATE INDEX "lossanddamage_tenant_id" ON "loss_and_damages" ("tenant_id");
-- Create "next_of_kins" table
CREATE TABLE "next_of_kins" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "full_name" character varying NOT NULL, "relationship" character varying NULL, "phone" character varying NULL, "email" character varying NULL, "address" character varying NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "nextofkin_employee_id" to table: "next_of_kins"
CREATE INDEX "nextofkin_employee_id" ON "next_of_kins" ("employee_id");
-- Create index "nextofkin_tenant_id" to table: "next_of_kins"
CREATE INDEX "nextofkin_tenant_id" ON "next_of_kins" ("tenant_id");
-- Create "outbox_events" table
CREATE TABLE "outbox_events" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "aggregate_type" character varying NOT NULL, "aggregate_id" character varying NOT NULL, "event_type" character varying NOT NULL, "payload" jsonb NOT NULL, "status" character varying NOT NULL DEFAULT 'PENDING', "attempts" bigint NOT NULL DEFAULT 0, "last_attempt_at" timestamptz NULL, "published_at" timestamptz NULL, "error_message" text NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "outboxevent_created_at" to table: "outbox_events"
CREATE INDEX "outboxevent_created_at" ON "outbox_events" ("created_at");
-- Create index "outboxevent_status" to table: "outbox_events"
CREATE INDEX "outboxevent_status" ON "outbox_events" ("status");
-- Create index "outboxevent_tenant_id_status" to table: "outbox_events"
CREATE INDEX "outboxevent_tenant_id_status" ON "outbox_events" ("tenant_id", "status");
-- Create "payroll_components" table
CREATE TABLE "payroll_components" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "wb_code" character varying NULL, "acc_code" character varying NULL, "title" character varying NOT NULL, "category" character varying NULL, "description" text NULL, "mode" character varying NULL, "non_cash" boolean NOT NULL DEFAULT false, "deduct_after_taxing" boolean NOT NULL DEFAULT false, "applicable_relief_id" uuid NULL, "applicable_tax_formula_id" uuid NULL, "checkoff" boolean NOT NULL DEFAULT true, "constant" boolean NOT NULL DEFAULT true, "statutory" boolean NOT NULL DEFAULT false, "is_active" boolean NOT NULL DEFAULT true, "taxable_status" character varying NULL, "deduction_phase" character varying NOT NULL DEFAULT 'before_tax', "deduction_priority" bigint NOT NULL DEFAULT 1, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "payrollcomponent_tenant_id" to table: "payroll_components"
CREATE INDEX "payrollcomponent_tenant_id" ON "payroll_components" ("tenant_id");
-- Create index "payrollcomponent_tenant_id_category" to table: "payroll_components"
CREATE INDEX "payrollcomponent_tenant_id_category" ON "payroll_components" ("tenant_id", "category");
-- Create "payroll_formulas" table
CREATE TABLE "payroll_formulas" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "type" character varying NOT NULL, "category" character varying NULL, "title" character varying NOT NULL, "unit" character varying NOT NULL DEFAULT 'KES', "effective_from" timestamptz NULL, "effective_to" timestamptz NULL, "upper_limit" numeric(10,4) NOT NULL, "upper_limit_amount" numeric(18,4) NOT NULL, "upper_limit_percentage" numeric(10,4) NOT NULL, "personal_relief" numeric(18,4) NOT NULL, "relief_carry_forward" boolean NOT NULL DEFAULT false, "min_taxable_income" numeric(18,4) NOT NULL, "progressive" boolean NOT NULL DEFAULT false, "component_id" uuid NULL, "version" character varying NOT NULL DEFAULT '1.0', "regulatory_source" character varying NULL, "notes" text NULL, "deduction_order" jsonb NULL, "is_current" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "payrollformula_tenant_id" to table: "payroll_formulas"
CREATE INDEX "payrollformula_tenant_id" ON "payroll_formulas" ("tenant_id");
-- Create index "payrollformula_tenant_id_type_category" to table: "payroll_formulas"
CREATE INDEX "payrollformula_tenant_id_type_category" ON "payroll_formulas" ("tenant_id", "type", "category");
-- Create index "payrollformula_tenant_id_type_category_effective_from" to table: "payroll_formulas"
CREATE INDEX "payrollformula_tenant_id_type_category_effective_from" ON "payroll_formulas" ("tenant_id", "type", "category", "effective_from");
-- Create index "uq_payroll_formula_current" to table: "payroll_formulas"
CREATE UNIQUE INDEX "uq_payroll_formula_current" ON "payroll_formulas" ("tenant_id", "type", "category") WHERE (is_current = true);
-- Create "payroll_formula_items" table
CREATE TABLE "payroll_formula_items" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "formula_id" uuid NOT NULL, "amount_from" numeric(18,4) NOT NULL, "amount_to" numeric(18,4) NOT NULL, "deduct_amount" numeric(18,4) NOT NULL, "deduct_percentage" numeric(10,4) NOT NULL, PRIMARY KEY ("id"));
-- Create index "payrollformulaitem_formula_id" to table: "payroll_formula_items"
CREATE INDEX "payrollformulaitem_formula_id" ON "payroll_formula_items" ("formula_id");
-- Create index "payrollformulaitem_tenant_id" to table: "payroll_formula_items"
CREATE INDEX "payrollformulaitem_tenant_id" ON "payroll_formula_items" ("tenant_id");
-- Create "payroll_reliefs" table
CREATE TABLE "payroll_reliefs" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "type" character varying NOT NULL, "title" character varying NOT NULL, "actual_amount" boolean NOT NULL DEFAULT true, "fixed_limit" numeric(18,4) NOT NULL, "percentage" numeric(10,4) NOT NULL, "percent_of" character varying NULL, "is_active" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "payrollrelief_tenant_id" to table: "payroll_reliefs"
CREATE INDEX "payrollrelief_tenant_id" ON "payroll_reliefs" ("tenant_id");
-- Create index "payrollrelief_tenant_id_type_is_active" to table: "payroll_reliefs"
CREATE INDEX "payrollrelief_tenant_id_type_is_active" ON "payroll_reliefs" ("tenant_id", "type", "is_active");
-- Create "payroll_split_ratios" table
CREATE TABLE "payroll_split_ratios" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "formula_id" uuid NOT NULL, "employee_percentage" numeric(10,4) NOT NULL, "employer_percentage" numeric(10,4) NOT NULL, PRIMARY KEY ("id"));
-- Create index "payrollsplitratio_formula_id" to table: "payroll_split_ratios"
CREATE INDEX "payrollsplitratio_formula_id" ON "payroll_split_ratios" ("formula_id");
-- Create index "payrollsplitratio_tenant_id" to table: "payroll_split_ratios"
CREATE INDEX "payrollsplitratio_tenant_id" ON "payroll_split_ratios" ("tenant_id");
-- Create "advances" table
CREATE TABLE "advances" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "approver_id" uuid NULL, "repay_option_id" uuid NULL, "approved" boolean NOT NULL DEFAULT false, "issue_date" timestamptz NULL, "prev_payment_date" timestamptz NULL, "next_payment_date" timestamptz NULL, "amount_issued" numeric(18,4) NOT NULL, "amount_repaid" numeric(18,4) NOT NULL, "is_active" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "advance_employee_id" to table: "advances"
CREATE INDEX "advance_employee_id" ON "advances" ("employee_id");
-- Create index "advance_employee_id_is_active" to table: "advances"
CREATE INDEX "advance_employee_id_is_active" ON "advances" ("employee_id", "is_active");
-- Create index "advance_tenant_id" to table: "advances"
CREATE INDEX "advance_tenant_id" ON "advances" ("tenant_id");
-- Create "payslip_audits" table
CREATE TABLE "payslip_audits" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "payslip_id" uuid NOT NULL, "action_by" uuid NULL, "action" character varying NOT NULL, "remarks" text NULL, "action_date" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "payslipaudit_payslip_id" to table: "payslip_audits"
CREATE INDEX "payslipaudit_payslip_id" ON "payslip_audits" ("payslip_id");
-- Create index "payslipaudit_tenant_id" to table: "payslip_audits"
CREATE INDEX "payslipaudit_tenant_id" ON "payslip_audits" ("tenant_id");
-- Create "regions" table
CREATE TABLE "regions" ("id" uuid NOT NULL, "tenant_id" uuid NULL, "code" character varying NULL, "name" character varying NOT NULL, "parent_region_id" uuid NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "region_code" to table: "regions"
CREATE INDEX "region_code" ON "regions" ("code");
-- Create index "region_tenant_id" to table: "regions"
CREATE INDEX "region_tenant_id" ON "regions" ("tenant_id");
-- Create "projects" table
CREATE TABLE "projects" ("id" uuid NOT NULL, "tenant_id" uuid NULL, "code" character varying NULL, "title" character varying NOT NULL, "category" character varying NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "project_code" to table: "projects"
CREATE INDEX "project_code" ON "projects" ("code");
-- Create index "project_tenant_id" to table: "projects"
CREATE INDEX "project_tenant_id" ON "projects" ("tenant_id");
-- Create "auth_outlets" table
CREATE TABLE "auth_outlets" ("id" uuid NOT NULL, "code" character varying NULL, "name" character varying NOT NULL, "use_case" character varying NULL, "is_hq" boolean NOT NULL DEFAULT false, "status" character varying NOT NULL DEFAULT 'active', "timezone" character varying NULL, "synced_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, "tenant_id" uuid NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "auth_outlets_auth_tenants_outlets" FOREIGN KEY ("tenant_id") REFERENCES "auth_tenants" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION);
-- Create index "authoutlet_status" to table: "auth_outlets"
CREATE INDEX "authoutlet_status" ON "auth_outlets" ("status");
-- Create index "authoutlet_tenant_id" to table: "auth_outlets"
CREATE INDEX "authoutlet_tenant_id" ON "auth_outlets" ("tenant_id");
-- Create index "authoutlet_tenant_id_code" to table: "auth_outlets"
CREATE INDEX "authoutlet_tenant_id_code" ON "auth_outlets" ("tenant_id", "code");
-- Create "bank_institutions" table
CREATE TABLE "bank_institutions" ("id" uuid NOT NULL, "name" character varying NOT NULL, "code" character varying NULL, "short_code" character varying NULL, "swift_code" character varying NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "bankinstitution_code" to table: "bank_institutions"
CREATE UNIQUE INDEX "bankinstitution_code" ON "bank_institutions" ("code");
-- Create index "bankinstitution_name" to table: "bank_institutions"
CREATE INDEX "bankinstitution_name" ON "bank_institutions" ("name");
-- Create "bank_branches" table
CREATE TABLE "bank_branches" ("id" uuid NOT NULL, "name" character varying NOT NULL, "code" character varying NULL, "created_at" timestamptz NOT NULL, "bank_id" uuid NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "bank_branches_bank_institutions_branches" FOREIGN KEY ("bank_id") REFERENCES "bank_institutions" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION);
-- Create index "bankbranch_bank_id" to table: "bank_branches"
CREATE INDEX "bankbranch_bank_id" ON "bank_branches" ("bank_id");
-- Create index "bankbranch_bank_id_code" to table: "bank_branches"
CREATE UNIQUE INDEX "bankbranch_bank_id_code" ON "bank_branches" ("bank_id", "code");
-- Create "permissions" table
CREATE TABLE "permissions" ("id" uuid NOT NULL, "permission_code" character varying NOT NULL, "name" character varying NOT NULL, "module" character varying NOT NULL, "action" character varying NOT NULL, "resource" character varying NULL, "description" text NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "permission_action" to table: "permissions"
CREATE INDEX "permission_action" ON "permissions" ("action");
-- Create index "permission_module" to table: "permissions"
CREATE INDEX "permission_module" ON "permissions" ("module");
-- Create index "permission_module_action" to table: "permissions"
CREATE INDEX "permission_module_action" ON "permissions" ("module", "action");
-- Create index "permission_permission_code" to table: "permissions"
CREATE UNIQUE INDEX "permission_permission_code" ON "permissions" ("permission_code");
-- Create index "permissions_permission_code_key" to table: "permissions"
CREATE UNIQUE INDEX "permissions_permission_code_key" ON "permissions" ("permission_code");
-- Create "roles" table
CREATE TABLE "roles" ("id" uuid NOT NULL, "tenant_id" uuid NULL, "role_code" character varying NOT NULL, "name" character varying NOT NULL, "description" text NULL, "is_system_role" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "role_is_system_role" to table: "roles"
CREATE INDEX "role_is_system_role" ON "roles" ("is_system_role");
-- Create index "role_role_code" to table: "roles"
CREATE INDEX "role_role_code" ON "roles" ("role_code");
-- Create index "role_tenant_id" to table: "roles"
CREATE INDEX "role_tenant_id" ON "roles" ("tenant_id");
-- Create index "role_tenant_id_role_code" to table: "roles"
CREATE UNIQUE INDEX "role_tenant_id_role_code" ON "roles" ("tenant_id", "role_code");
-- Create "role_permissions" table
CREATE TABLE "role_permissions" ("id" bigint NOT NULL GENERATED BY DEFAULT AS IDENTITY, "role_id" uuid NOT NULL, "permission_id" uuid NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "role_permissions_permissions_permission" FOREIGN KEY ("permission_id") REFERENCES "permissions" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION, CONSTRAINT "role_permissions_roles_role" FOREIGN KEY ("role_id") REFERENCES "roles" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION);
-- Create index "rolepermission_permission_id" to table: "role_permissions"
CREATE INDEX "rolepermission_permission_id" ON "role_permissions" ("permission_id");
-- Create index "rolepermission_role_id" to table: "role_permissions"
CREATE INDEX "rolepermission_role_id" ON "role_permissions" ("role_id");
-- Create index "rolepermission_role_id_permission_id" to table: "role_permissions"
CREATE UNIQUE INDEX "rolepermission_role_id_permission_id" ON "role_permissions" ("role_id", "permission_id");
-- Create "custom_users" table
CREATE TABLE "custom_users" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "external_id" character varying NOT NULL, "email" character varying NOT NULL, "first_name" character varying NULL, "last_name" character varying NULL, "middle_name" character varying NULL, "phone" character varying NULL, "signature_url" character varying NULL, "timezone" character varying NULL, "is_active" boolean NOT NULL DEFAULT true, "is_staff" boolean NOT NULL DEFAULT false, "is_superuser" boolean NOT NULL DEFAULT false, "sync_status" character varying NOT NULL DEFAULT 'synced', "last_sync_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "custom_users_external_id_key" to table: "custom_users"
CREATE UNIQUE INDEX "custom_users_external_id_key" ON "custom_users" ("external_id");
-- Create index "customuser_email" to table: "custom_users"
CREATE INDEX "customuser_email" ON "custom_users" ("email");
-- Create index "customuser_external_id" to table: "custom_users"
CREATE UNIQUE INDEX "customuser_external_id" ON "custom_users" ("external_id");
-- Create index "customuser_tenant_id" to table: "custom_users"
CREATE INDEX "customuser_tenant_id" ON "custom_users" ("tenant_id");
-- Create index "customuser_tenant_id_email" to table: "custom_users"
CREATE INDEX "customuser_tenant_id_email" ON "custom_users" ("tenant_id", "email");
-- Create "user_role_assignments" table
CREATE TABLE "user_role_assignments" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "assigned_at" timestamptz NOT NULL, "expires_at" timestamptz NULL, "user_id" uuid NOT NULL, "role_id" uuid NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "user_role_assignments_custom_users_role_assignments" FOREIGN KEY ("user_id") REFERENCES "custom_users" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION, CONSTRAINT "user_role_assignments_roles_user_assignments" FOREIGN KEY ("role_id") REFERENCES "roles" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION);
-- Create index "userroleassignment_role_id" to table: "user_role_assignments"
CREATE INDEX "userroleassignment_role_id" ON "user_role_assignments" ("role_id");
-- Create index "userroleassignment_tenant_id" to table: "user_role_assignments"
CREATE INDEX "userroleassignment_tenant_id" ON "user_role_assignments" ("tenant_id");
-- Create index "userroleassignment_tenant_id_user_id_role_id" to table: "user_role_assignments"
CREATE UNIQUE INDEX "userroleassignment_tenant_id_user_id_role_id" ON "user_role_assignments" ("tenant_id", "user_id", "role_id");
-- Create index "userroleassignment_user_id" to table: "user_role_assignments"
CREATE INDEX "userroleassignment_user_id" ON "user_role_assignments" ("user_id");
