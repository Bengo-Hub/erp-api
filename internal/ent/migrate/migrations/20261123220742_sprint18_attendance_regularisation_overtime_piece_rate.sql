-- Create "attendance_regularisations" table
CREATE TABLE "attendance_regularisations" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "record_id" uuid NULL, "date" timestamptz NOT NULL, "check_in" timestamptz NULL, "check_out" timestamptz NULL, "reason" text NOT NULL, "status" character varying NOT NULL DEFAULT 'pending', "approval_request_id" uuid NULL, "before" jsonb NULL, "requested_by" uuid NULL, "decided_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "attendanceregularisation_tenant_id_employee_id_date" to table: "attendance_regularisations"
CREATE INDEX "attendanceregularisation_tenant_id_employee_id_date" ON "attendance_regularisations" ("tenant_id", "employee_id", "date");
-- Create index "attendanceregularisation_tenant_id_status" to table: "attendance_regularisations"
CREATE INDEX "attendanceregularisation_tenant_id_status" ON "attendance_regularisations" ("tenant_id", "status");
-- Create "overtime_requests" table
CREATE TABLE "overtime_requests" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "date" timestamptz NOT NULL, "hours" numeric(8,2) NOT NULL, "reason" text NULL, "status" character varying NOT NULL DEFAULT 'pending', "approval_request_id" uuid NULL, "requested_by" uuid NULL, "decided_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "overtimerequest_tenant_id_employee_id_date" to table: "overtime_requests"
CREATE INDEX "overtimerequest_tenant_id_employee_id_date" ON "overtime_requests" ("tenant_id", "employee_id", "date");
-- Create index "overtimerequest_tenant_id_status" to table: "overtime_requests"
CREATE INDEX "overtimerequest_tenant_id_status" ON "overtime_requests" ("tenant_id", "status");
-- Create "piece_outputs" table
CREATE TABLE "piece_outputs" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "piece_rate_id" uuid NOT NULL, "date" timestamptz NOT NULL, "quantity" numeric(14,3) NOT NULL, "rejected_quantity" numeric(14,3) NOT NULL, "rate" numeric(18,4) NOT NULL, "amount" numeric(18,4) NOT NULL, "currency" character varying NOT NULL, "note" text NULL, "status" character varying NOT NULL DEFAULT 'pending', "recorded_by" uuid NULL, "reviewed_by" uuid NULL, "reviewed_at" timestamptz NULL, "payslip_id" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "pieceoutput_tenant_id_date" to table: "piece_outputs"
CREATE INDEX "pieceoutput_tenant_id_date" ON "piece_outputs" ("tenant_id", "date");
-- Create index "pieceoutput_tenant_id_employee_id_date" to table: "piece_outputs"
CREATE INDEX "pieceoutput_tenant_id_employee_id_date" ON "piece_outputs" ("tenant_id", "employee_id", "date");
-- Create index "pieceoutput_tenant_id_status" to table: "piece_outputs"
CREATE INDEX "pieceoutput_tenant_id_status" ON "piece_outputs" ("tenant_id", "status");
-- Create "piece_rates" table
CREATE TABLE "piece_rates" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "code" character varying NOT NULL, "name" character varying NOT NULL, "unit" character varying NOT NULL, "rate" numeric(18,4) NOT NULL, "currency" character varying NOT NULL, "department_id" uuid NULL, "effective_from" timestamptz NOT NULL, "effective_to" timestamptz NULL, "active" boolean NOT NULL DEFAULT true, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "piecerate_tenant_id" to table: "piece_rates"
CREATE INDEX "piecerate_tenant_id" ON "piece_rates" ("tenant_id");
-- Create index "piecerate_tenant_id_code" to table: "piece_rates"
CREATE INDEX "piecerate_tenant_id_code" ON "piece_rates" ("tenant_id", "code");
