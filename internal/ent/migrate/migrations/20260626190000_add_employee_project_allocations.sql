-- Employee/consultant ↔ project allocations (% or fixed amount per project, with own dates).
CREATE TABLE "employee_project_allocations" (
  "id" uuid NOT NULL,
  "tenant_id" uuid NOT NULL,
  "employee_id" uuid NOT NULL,
  "project_id" uuid NOT NULL,
  "project_name" character varying NULL,
  "cost_center_id" uuid NULL,
  "allocation_percent" numeric(18,4) NOT NULL,
  "fixed_amount" double precision NULL,
  "start_date" timestamptz NULL,
  "end_date" timestamptz NULL,
  "is_active" boolean NOT NULL DEFAULT true,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  PRIMARY KEY ("id")
);
CREATE INDEX "employeeprojectallocation_tenant_id" ON "employee_project_allocations" ("tenant_id");
CREATE INDEX "employeeprojectallocation_tenant_id_employee_id" ON "employee_project_allocations" ("tenant_id", "employee_id");
CREATE INDEX "employeeprojectallocation_tenant_id_project_id" ON "employee_project_allocations" ("tenant_id", "project_id");
