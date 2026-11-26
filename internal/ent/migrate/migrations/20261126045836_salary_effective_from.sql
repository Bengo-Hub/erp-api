-- Modify "salary_details" table
ALTER TABLE "salary_details" ADD COLUMN "effective_from" timestamptz NULL;
-- Create index "salarydetails_tenant_id_employee_id_effective_from" to table: "salary_details"
CREATE INDEX "salarydetails_tenant_id_employee_id_effective_from" ON "salary_details" ("tenant_id", "employee_id", "effective_from");
