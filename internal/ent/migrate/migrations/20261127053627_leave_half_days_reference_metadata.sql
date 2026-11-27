-- Modify "claim_items" table
ALTER TABLE "claim_items" ADD COLUMN "item_date" timestamptz NULL;
-- Modify "contracts" table
ALTER TABLE "contracts" ADD COLUMN "metadata" jsonb NULL;
-- Modify "departments" table
ALTER TABLE "departments" ADD COLUMN "metadata" jsonb NULL;
-- Modify "job_groups" table
ALTER TABLE "job_groups" ADD COLUMN "metadata" jsonb NULL;
-- Modify "job_titles" table
ALTER TABLE "job_titles" ADD COLUMN "metadata" jsonb NULL;
-- Modify "leave_requests" table
ALTER TABLE "leave_requests" ADD COLUMN "start_half_day" boolean NOT NULL DEFAULT false, ADD COLUMN "end_half_day" boolean NOT NULL DEFAULT false;
