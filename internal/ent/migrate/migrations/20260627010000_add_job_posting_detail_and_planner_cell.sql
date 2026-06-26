-- Recruitment job-posting detail + drawable shift-planner cell support.
-- All columns are nullable, so this applies online (additive) on populated tables — no backfill.

-- job_postings: rich-text requirements/responsibilities + advertised salary range.
ALTER TABLE "job_postings" ADD COLUMN IF NOT EXISTS "requirements" text NULL;
ALTER TABLE "job_postings" ADD COLUMN IF NOT EXISTS "responsibilities" text NULL;
ALTER TABLE "job_postings" ADD COLUMN IF NOT EXISTS "salary_min" character varying NULL;
ALTER TABLE "job_postings" ADD COLUMN IF NOT EXISTS "salary_max" character varying NULL;
ALTER TABLE "job_postings" ADD COLUMN IF NOT EXISTS "salary_currency" character varying NULL;

-- staff_shift_overrides: link a planner cell to a named work shift.
ALTER TABLE "staff_shift_overrides" ADD COLUMN IF NOT EXISTS "work_shift_id" uuid NULL;
