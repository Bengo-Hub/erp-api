-- Modify "departments" table: link a department to the treasury cost center that absorbs its
-- unallocated payroll cost.
ALTER TABLE "departments" ADD COLUMN "cost_center_id" uuid NULL;
