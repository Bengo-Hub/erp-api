-- Create "attendance_deductions" table: reviewable lateness and unexcused-absence deductions per
-- employee and payroll month (approved rows are deducted as unpaid time by the payroll run).
CREATE TABLE "attendance_deductions" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "period" timestamptz NOT NULL, "kind" character varying NOT NULL, "occurrences" bigint NOT NULL DEFAULT 0, "minutes" bigint NOT NULL DEFAULT 0, "amount" numeric(18,4) NOT NULL, "basis" character varying NOT NULL, "rule_id" uuid NULL, "status" character varying NOT NULL DEFAULT 'pending', "reviewed_by" uuid NULL, "reviewed_at" timestamptz NULL, "note" character varying NULL, "payslip_id" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "attendancededuction_tenant_id_employee_id_period_kind" to table: "attendance_deductions"
CREATE UNIQUE INDEX "attendancededuction_tenant_id_employee_id_period_kind" ON "attendance_deductions" ("tenant_id", "employee_id", "period", "kind");
-- Create index "attendancededuction_tenant_id_period_status" to table: "attendance_deductions"
CREATE INDEX "attendancededuction_tenant_id_period_status" ON "attendance_deductions" ("tenant_id", "period", "status");
