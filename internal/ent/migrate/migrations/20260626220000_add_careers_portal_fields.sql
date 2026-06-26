-- Public careers portal fields. All columns are nullable or have a SQL default, so this applies
-- online (additive) on populated tables — no backfill needed.

-- job_postings: slug, visibility, employment type, openings, application deadline.
ALTER TABLE "job_postings" ADD COLUMN "slug" character varying NULL;
ALTER TABLE "job_postings" ADD COLUMN "is_public" boolean NOT NULL DEFAULT false;
ALTER TABLE "job_postings" ADD COLUMN "employment_type" character varying NULL;
ALTER TABLE "job_postings" ADD COLUMN "num_positions" bigint NOT NULL DEFAULT 1;
ALTER TABLE "job_postings" ADD COLUMN "application_deadline" timestamptz NULL;

-- applications: applicant cover letter + source channel.
ALTER TABLE "applications" ADD COLUMN "cover_letter" text NULL;
ALTER TABLE "applications" ADD COLUMN "source" character varying NULL;
