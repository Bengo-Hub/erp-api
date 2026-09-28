-- Modify "employees" table: record when an employee was terminated, so exits and turnover can be
-- counted per period. Existing terminated employees keep a NULL date (their exit date is unknown).
ALTER TABLE "employees" ADD COLUMN "terminated_at" timestamptz NULL;
-- Create index "employee_tenant_id_terminated_at" to table: "employees"
CREATE INDEX "employee_tenant_id_terminated_at" ON "employees" ("tenant_id", "terminated_at");
