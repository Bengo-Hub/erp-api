-- Create "leave_balances" table
CREATE TABLE "leave_balances" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "category_id" uuid NOT NULL, "year" bigint NOT NULL, "days_entitled" numeric(7,2) NOT NULL, "days_taken" numeric(7,2) NOT NULL, "days_remaining" numeric(7,2) NOT NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "leavebalance_tenant_id" to table: "leave_balances"
CREATE INDEX "leavebalance_tenant_id" ON "leave_balances" ("tenant_id");
-- Create index "leavebalance_tenant_id_employee_id_category_id_year" to table: "leave_balances"
CREATE UNIQUE INDEX "leavebalance_tenant_id_employee_id_category_id_year" ON "leave_balances" ("tenant_id", "employee_id", "category_id", "year");
-- Create "leave_categories" table
CREATE TABLE "leave_categories" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "name" character varying NOT NULL, "description" character varying NULL, "is_active" boolean NOT NULL DEFAULT true, "default_annual_days" numeric(7,2) NOT NULL, "allow_carryover" boolean NOT NULL DEFAULT false, "max_carryover_days" numeric(7,2) NOT NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "leavecategory_tenant_id" to table: "leave_categories"
CREATE INDEX "leavecategory_tenant_id" ON "leave_categories" ("tenant_id");
-- Create index "leavecategory_tenant_id_is_active" to table: "leave_categories"
CREATE INDEX "leavecategory_tenant_id_is_active" ON "leave_categories" ("tenant_id", "is_active");
-- Create index "leavecategory_tenant_id_name" to table: "leave_categories"
CREATE UNIQUE INDEX "leavecategory_tenant_id_name" ON "leave_categories" ("tenant_id", "name");
-- Create "leave_entitlements" table
CREATE TABLE "leave_entitlements" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "category_id" uuid NOT NULL, "days_entitled" numeric(7,2) NOT NULL, "year" bigint NOT NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "leaveentitlement_tenant_id" to table: "leave_entitlements"
CREATE INDEX "leaveentitlement_tenant_id" ON "leave_entitlements" ("tenant_id");
-- Create index "leaveentitlement_tenant_id_employee_id_category_id_year" to table: "leave_entitlements"
CREATE UNIQUE INDEX "leaveentitlement_tenant_id_employee_id_category_id_year" ON "leave_entitlements" ("tenant_id", "employee_id", "category_id", "year");
-- Create "leave_logs" table
CREATE TABLE "leave_logs" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "leave_request_id" uuid NOT NULL, "action" character varying NOT NULL, "description" character varying NULL, "user_id" uuid NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "leavelog_tenant_id" to table: "leave_logs"
CREATE INDEX "leavelog_tenant_id" ON "leave_logs" ("tenant_id");
-- Create index "leavelog_tenant_id_leave_request_id" to table: "leave_logs"
CREATE INDEX "leavelog_tenant_id_leave_request_id" ON "leave_logs" ("tenant_id", "leave_request_id");
-- Create "leave_requests" table
CREATE TABLE "leave_requests" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "category_id" uuid NOT NULL, "start_date" timestamptz NOT NULL, "end_date" timestamptz NOT NULL, "days_requested" numeric(7,2) NOT NULL, "reason" character varying NULL, "status" character varying NOT NULL DEFAULT 'pending', "approved_by" uuid NULL, "approved_at" timestamptz NULL, "rejection_reason" character varying NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "leaverequest_tenant_id" to table: "leave_requests"
CREATE INDEX "leaverequest_tenant_id" ON "leave_requests" ("tenant_id");
-- Create index "leaverequest_tenant_id_employee_id" to table: "leave_requests"
CREATE INDEX "leaverequest_tenant_id_employee_id" ON "leave_requests" ("tenant_id", "employee_id");
-- Create index "leaverequest_tenant_id_status" to table: "leave_requests"
CREATE INDEX "leaverequest_tenant_id_status" ON "leave_requests" ("tenant_id", "status");
-- Create "public_holidays" table
CREATE TABLE "public_holidays" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "name" character varying NOT NULL, "date" timestamptz NOT NULL, "is_national" boolean NOT NULL DEFAULT true, "county" character varying NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "publicholiday_tenant_id" to table: "public_holidays"
CREATE INDEX "publicholiday_tenant_id" ON "public_holidays" ("tenant_id");
-- Create index "publicholiday_tenant_id_date" to table: "public_holidays"
CREATE INDEX "publicholiday_tenant_id_date" ON "public_holidays" ("tenant_id", "date");
-- Create index "publicholiday_tenant_id_date_county" to table: "public_holidays"
CREATE UNIQUE INDEX "publicholiday_tenant_id_date_county" ON "public_holidays" ("tenant_id", "date", "county");
