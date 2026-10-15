-- Create "payroll_run_jobs" table: background payroll runs with progress (one active run per
-- tenant via the unique (tenant_id, active_lock) index; active_lock is NULL once finished).
CREATE TABLE "payroll_run_jobs" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "period" timestamptz NOT NULL, "status" character varying NOT NULL DEFAULT 'queued', "params" jsonb NULL, "total" bigint NOT NULL DEFAULT 0, "done" bigint NOT NULL DEFAULT 0, "payslips" bigint NOT NULL DEFAULT 0, "error" character varying NULL, "active_lock" character varying NULL, "created_by" uuid NULL, "started_at" timestamptz NULL, "finished_at" timestamptz NULL, "heartbeat_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "payrollrunjob_active_lock_heartbeat_at" to table: "payroll_run_jobs"
CREATE INDEX "payrollrunjob_active_lock_heartbeat_at" ON "payroll_run_jobs" ("active_lock", "heartbeat_at");
-- Create index "payrollrunjob_tenant_id_active_lock" to table: "payroll_run_jobs"
CREATE UNIQUE INDEX "payrollrunjob_tenant_id_active_lock" ON "payroll_run_jobs" ("tenant_id", "active_lock");
-- Create index "payrollrunjob_tenant_id_created_at" to table: "payroll_run_jobs"
CREATE INDEX "payrollrunjob_tenant_id_created_at" ON "payroll_run_jobs" ("tenant_id", "created_at");
