-- Expense claims: analytic (project/cost-center) + tax-treatment fields for finance posting.
ALTER TABLE "expense_claims" ADD COLUMN "project_id" uuid NULL;
ALTER TABLE "expense_claims" ADD COLUMN "cost_center_id" uuid NULL;
ALTER TABLE "expense_claims" ADD COLUMN "claim_type" character varying NOT NULL DEFAULT 'reimbursement';
ALTER TABLE "expense_claims" ADD COLUMN "taxable" boolean NOT NULL DEFAULT false;
