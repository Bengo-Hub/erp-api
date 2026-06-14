-- Modify "employee_bank_accounts" table
ALTER TABLE "employee_bank_accounts" DROP COLUMN "bank_institution_id", DROP COLUMN "bank_branch_id", ADD COLUMN "bank_name" character varying NULL, ADD COLUMN "bank_code" character varying NULL, ADD COLUMN "branch_name" character varying NULL, ADD COLUMN "branch_code" character varying NULL;
-- Drop the project + bank-master tables: these domains belong to projects-service and
-- treasury/payment-rail reference respectively (Part A data-ownership conformance).
-- bank_branches has an FK to bank_institutions, so drop it first.
DROP TABLE IF EXISTS "bank_branches";
DROP TABLE IF EXISTS "bank_institutions";
DROP TABLE IF EXISTS "projects";
