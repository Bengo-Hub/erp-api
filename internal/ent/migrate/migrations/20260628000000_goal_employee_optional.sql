-- Modify "goals" table: employee_id is nullable for reusable library templates.
ALTER TABLE "goals" ALTER COLUMN "employee_id" DROP NOT NULL;
