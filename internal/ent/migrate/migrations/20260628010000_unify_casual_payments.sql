-- Unified casual-payments register (wingubox): one row per casual payment, covering both a
-- direct payout to a registered casual employee (quantity x rate) and a reimbursement to a
-- PM/consultant who paid an informal worker. Folds + retires casual_labor_records.
CREATE TABLE "casual_payments" (
  "id" uuid NOT NULL,
  "tenant_id" uuid NOT NULL,
  "settlement_mode" character varying NOT NULL DEFAULT 'direct_payout',
  "employee_id" uuid NULL,
  "worker_name" character varying NULL,
  "worker_id_number" character varying NULL,
  "worker_phone" character varying NULL,
  "engaged_by_employee_id" uuid NULL,
  "imprest_advance_id" uuid NULL,
  "wage_type" character varying NOT NULL DEFAULT 'daily_wages',
  "quantity" numeric(7,2) NOT NULL,
  "rate" numeric(18,4) NOT NULL,
  "amount" numeric(18,4) NOT NULL,
  "task_description" character varying NULL,
  "work_date" timestamptz NULL,
  "payment_date" timestamptz NULL,
  "payroll_month" timestamptz NULL,
  "project_id" uuid NULL,
  "cost_center_id" uuid NULL,
  "payment_option" character varying NULL,
  "status" character varying NOT NULL DEFAULT 'pending',
  "approver_id" uuid NULL,
  "approved_at" timestamptz NULL,
  "attachment_url" character varying NULL,
  "delete_status" boolean NOT NULL DEFAULT false,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  PRIMARY KEY ("id")
);
CREATE INDEX "casualpayment_tenant_id" ON "casual_payments" ("tenant_id");
CREATE INDEX "casualpayment_tenant_id_settlement_mode" ON "casual_payments" ("tenant_id", "settlement_mode");
CREATE INDEX "casualpayment_tenant_id_payroll_month" ON "casual_payments" ("tenant_id", "payroll_month");
CREATE INDEX "casualpayment_tenant_id_employee_id" ON "casual_payments" ("tenant_id", "employee_id");
CREATE INDEX "casualpayment_tenant_id_project_id" ON "casual_payments" ("tenant_id", "project_id");

-- Fold any existing informal-worker records into the unified table as reimburse_engager / lump_sum
-- (quantity 1 x rate amount). Guarded so the migration is a no-op when the old table is absent.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'casual_labor_records') THEN
    INSERT INTO "casual_payments" (
      "id", "tenant_id", "settlement_mode", "worker_name", "worker_id_number", "worker_phone",
      "engaged_by_employee_id", "imprest_advance_id", "wage_type", "quantity", "rate", "amount",
      "task_description", "work_date", "payment_option", "project_id", "cost_center_id",
      "status", "approver_id", "approved_at", "attachment_url", "delete_status", "created_at", "updated_at"
    )
    SELECT
      "id", "tenant_id", 'reimburse_engager', "worker_name", "worker_id_number", "worker_phone",
      "engaged_by_employee_id", "imprest_advance_id", 'lump_sum', 1, "amount", "amount",
      "task_description", "work_date", "payment_method", "project_id", "cost_center_id",
      "status", "approver_id", "approved_at", "attachment_url", "delete_status", "created_at", "updated_at"
    FROM "casual_labor_records";

    DROP TABLE "casual_labor_records";
  END IF;
END $$;
