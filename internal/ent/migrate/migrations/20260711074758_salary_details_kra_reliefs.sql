-- Modify "salary_details" table: add per-employee KRA relief inputs (insurance premium,
-- pension contribution, mortgage interest, PWD disability-exemption flag). Money columns default
-- to 0 at the application layer (ent moneyField); disability_exempt defaults false.
ALTER TABLE "salary_details" ADD COLUMN "insurance_premium" numeric(18,4) NOT NULL DEFAULT 0, ADD COLUMN "pension_contribution" numeric(18,4) NOT NULL DEFAULT 0, ADD COLUMN "mortgage_interest" numeric(18,4) NOT NULL DEFAULT 0, ADD COLUMN "disability_exempt" boolean NOT NULL DEFAULT false;
ALTER TABLE "salary_details" ALTER COLUMN "insurance_premium" DROP DEFAULT, ALTER COLUMN "pension_contribution" DROP DEFAULT, ALTER COLUMN "mortgage_interest" DROP DEFAULT;
