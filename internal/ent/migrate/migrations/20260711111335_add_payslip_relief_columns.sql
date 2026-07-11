-- Modify "payslips" table: persist the itemised KRA reliefs the engine applied (insurance credit,
-- deductible pension, mortgage interest, PWD exemption) for the P9/P9A card. Default 0.
ALTER TABLE "payslips" ADD COLUMN "insurance_relief" numeric(18,4) NOT NULL DEFAULT 0, ADD COLUMN "pension_deduction" numeric(18,4) NOT NULL DEFAULT 0, ADD COLUMN "mortgage_deduction" numeric(18,4) NOT NULL DEFAULT 0, ADD COLUMN "disability_exemption" numeric(18,4) NOT NULL DEFAULT 0;
ALTER TABLE "payslips" ALTER COLUMN "insurance_relief" DROP DEFAULT, ALTER COLUMN "pension_deduction" DROP DEFAULT, ALTER COLUMN "mortgage_deduction" DROP DEFAULT, ALTER COLUMN "disability_exemption" DROP DEFAULT;
