-- Fix pre-existing varchar->text drift on casual_labor_records.task_description.
ALTER TABLE "casual_labor_records" ALTER COLUMN "task_description" TYPE text;
-- Payroll components: default monetary config (employee + employer side), per-unit earnings
-- and effective dates. Added nullable, backfilled to 0, then set NOT NULL so existing rows do
-- not violate NOT NULL and the final shape matches the ent schema (NOT NULL, no DB default).
ALTER TABLE "payroll_components"
  ADD COLUMN "amount" numeric(18,4) NULL,
  ADD COLUMN "percentage" numeric(10,4) NULL,
  ADD COLUMN "percent_of" character varying NULL,
  ADD COLUMN "employer_amount" numeric(18,4) NULL,
  ADD COLUMN "employer_percentage" numeric(10,4) NULL,
  ADD COLUMN "registration_no" character varying NULL,
  ADD COLUMN "unit_type" character varying NULL,
  ADD COLUMN "unit_rate" numeric(18,4) NULL,
  ADD COLUMN "quantity" numeric(7,2) NULL,
  ADD COLUMN "effective_from" timestamptz NULL,
  ADD COLUMN "effective_to" timestamptz NULL;
UPDATE "payroll_components"
  SET "amount" = 0, "percentage" = 0, "employer_amount" = 0,
      "employer_percentage" = 0, "unit_rate" = 0, "quantity" = 0
  WHERE "amount" IS NULL;
ALTER TABLE "payroll_components"
  ALTER COLUMN "amount" SET NOT NULL,
  ALTER COLUMN "percentage" SET NOT NULL,
  ALTER COLUMN "employer_amount" SET NOT NULL,
  ALTER COLUMN "employer_percentage" SET NOT NULL,
  ALTER COLUMN "unit_rate" SET NOT NULL,
  ALTER COLUMN "quantity" SET NOT NULL;
