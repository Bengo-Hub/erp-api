-- Onboarding task due dates + richer hiring-pipeline context. All nullable → online-additive safe.
ALTER TABLE "onboarding_tasks" ADD COLUMN "due_date" timestamptz NULL;

ALTER TABLE "applications" ADD COLUMN "interview_date" timestamptz NULL;
ALTER TABLE "applications" ADD COLUMN "offer_details" text NULL;
ALTER TABLE "applications" ADD COLUMN "rejection_reason" character varying NULL;
