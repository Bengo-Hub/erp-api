-- An employee's standard work shift: its weekly hours are the person's capacity for projects-api's
-- workload. Nullable, so the online migration adds it to existing rows without a default.
-- Modify "employees" table
ALTER TABLE "employees" ADD COLUMN "work_shift_id" uuid NULL;
