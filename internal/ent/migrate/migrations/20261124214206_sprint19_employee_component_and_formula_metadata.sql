-- Modify "employee_benefits" table
ALTER TABLE "employee_benefits" ADD COLUMN "metadata" jsonb NULL;
-- Modify "payroll_formulas" table
ALTER TABLE "payroll_formulas" ADD COLUMN "metadata" jsonb NULL;
