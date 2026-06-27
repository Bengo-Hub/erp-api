-- Modify "leave_categories" table
ALTER TABLE "leave_categories" ADD COLUMN "is_paid" boolean NOT NULL DEFAULT true;
-- Modify "appraisal_questions" table
ALTER TABLE "appraisal_questions" ADD COLUMN "category" character varying NULL, ADD COLUMN "weight" double precision NULL, ADD COLUMN "max_score" bigint NULL;
