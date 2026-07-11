-- Modify "salary_details" table: add per-employee KRA relief inputs (insurance premium,
-- pension contribution, mortgage interest, PWD disability-exemption flag). Money columns default
-- to 0 at the application layer (ent moneyField); disability_exempt defaults false.
ALTER TABLE "salary_details" ADD COLUMN "insurance_premium" numeric(18,4) NOT NULL, ADD COLUMN "pension_contribution" numeric(18,4) NOT NULL, ADD COLUMN "mortgage_interest" numeric(18,4) NOT NULL, ADD COLUMN "disability_exempt" boolean NOT NULL DEFAULT false;
