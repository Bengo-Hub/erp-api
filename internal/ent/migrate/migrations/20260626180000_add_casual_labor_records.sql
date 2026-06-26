-- Casual / subcontracted labour register: documented, approvable records of casual workers hired
-- (e.g. by a PM/consultant) for a task, with GL posting + project attribution.
CREATE TABLE "casual_labor_records" (
  "id" uuid NOT NULL,
  "tenant_id" uuid NOT NULL,
  "engaged_by_employee_id" uuid NULL,
  "project_id" uuid NULL,
  "cost_center_id" uuid NULL,
  "worker_name" character varying NOT NULL,
  "worker_id_number" character varying NULL,
  "worker_phone" character varying NULL,
  "task_description" character varying NULL,
  "amount" numeric(18,4) NOT NULL,
  "work_date" timestamptz NULL,
  "payment_method" character varying NULL,
  "status" character varying NOT NULL DEFAULT 'pending',
  "approver_id" uuid NULL,
  "approved_at" timestamptz NULL,
  "imprest_advance_id" uuid NULL,
  "attachment_url" character varying NULL,
  "delete_status" boolean NOT NULL DEFAULT false,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  PRIMARY KEY ("id")
);
CREATE INDEX "casuallaborrecord_tenant_id" ON "casual_labor_records" ("tenant_id");
CREATE INDEX "casuallaborrecord_tenant_id_project_id" ON "casual_labor_records" ("tenant_id", "project_id");
CREATE INDEX "casuallaborrecord_tenant_id_engaged_by_employee_id" ON "casual_labor_records" ("tenant_id", "engaged_by_employee_id");
