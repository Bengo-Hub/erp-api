-- Modify "salary_details" table: add the per-employee preferred net-pay disbursement channel
-- (default bank_transfer, safe on populated tables) + optional mobile-money payout phone.
ALTER TABLE "salary_details" ADD COLUMN "preferred_payout_method" character varying NOT NULL DEFAULT 'bank_transfer', ADD COLUMN "payout_phone" character varying NULL;
