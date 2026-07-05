-- POS↔ERP staff-credit: a POS staff purchase (goods on credit/layaway funded from salary) becomes a
-- StaffPurchaseDeduction recoverable that payroll recovers over installments. recovery_lines freeze
-- each period's recovered amount per recoverable (loan/advance/loss-damage/staff-purchase) so the
-- disburse step writes the amount back to the recoverable exactly once (the missing §2.7 write-back).
CREATE TABLE "staff_purchase_deductions" (
  "id" uuid NOT NULL,
  "tenant_id" uuid NOT NULL,
  "employee_id" uuid NOT NULL,
  "origin" character varying NOT NULL,
  "pos_reference" character varying NULL,
  "source_key" character varying NOT NULL,
  "principal" numeric(18,4) NOT NULL DEFAULT 0,
  "amount_recovered" numeric(18,4) NOT NULL DEFAULT 0,
  "installment_amount" numeric(18,4) NOT NULL DEFAULT 0,
  "installments_total" bigint NULL,
  "status" character varying NOT NULL DEFAULT 'active',
  "is_active" boolean NOT NULL DEFAULT true,
  "last_settled_batch" character varying NULL,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  PRIMARY KEY ("id")
);
CREATE INDEX "staffpurchasededuction_tenant_id" ON "staff_purchase_deductions" ("tenant_id");
CREATE INDEX "staffpurchasededuction_employee_id_is_active" ON "staff_purchase_deductions" ("employee_id", "is_active");
CREATE UNIQUE INDEX "staffpurchasededuction_tenant_id_source_key" ON "staff_purchase_deductions" ("tenant_id", "source_key");

CREATE TABLE "recovery_lines" (
  "id" uuid NOT NULL,
  "tenant_id" uuid NOT NULL,
  "payslip_id" uuid NOT NULL,
  "employee_id" uuid NOT NULL,
  "recoverable_type" character varying NOT NULL,
  "recoverable_id" uuid NOT NULL,
  "amount" numeric(18,4) NOT NULL DEFAULT 0,
  "batch_ref" character varying NULL,
  "applied" boolean NOT NULL DEFAULT false,
  "created_at" timestamptz NOT NULL,
  PRIMARY KEY ("id")
);
CREATE INDEX "recoveryline_tenant_id" ON "recovery_lines" ("tenant_id");
CREATE INDEX "recoveryline_payslip_id" ON "recovery_lines" ("payslip_id");
CREATE INDEX "recoveryline_tenant_id_applied" ON "recovery_lines" ("tenant_id", "applied");
CREATE UNIQUE INDEX "recoveryline_payslip_id_recoverable_type_recoverable_id" ON "recovery_lines" ("payslip_id", "recoverable_type", "recoverable_id");
