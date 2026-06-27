-- Consultant WHT payment vouchers: professional fees paid to consultants (employment_type=
-- consultant), subject to withholding tax (resident 5% / non-resident 20%), NOT PAYE. net =
-- gross - wht - deductions. On approval treasury posts DR 5600 / CR 2050 (net) / CR 2550 (WHT).
CREATE TABLE "consultant_vouchers" (
  "id" uuid NOT NULL,
  "tenant_id" uuid NOT NULL,
  "employee_id" uuid NOT NULL,
  "doc_number" character varying NULL,
  "title" character varying NULL,
  "period" timestamptz NULL,
  "gross_amount" numeric(18,4) NOT NULL,
  "deductions_amount" numeric(18,4) NOT NULL,
  "wht_rate" numeric(10,4) NOT NULL,
  "wht_amount" numeric(18,4) NOT NULL,
  "net_amount" numeric(18,4) NOT NULL,
  "is_resident" boolean NOT NULL DEFAULT true,
  "currency" character varying NOT NULL DEFAULT 'KES',
  "project_id" uuid NULL,
  "cost_center_id" uuid NULL,
  "status" character varying NOT NULL DEFAULT 'draft',
  "email_status" character varying NOT NULL DEFAULT 'Draft',
  "published" boolean NOT NULL DEFAULT false,
  "batch_ref" character varying NULL,
  "created_by" uuid NULL,
  "approver_id" uuid NULL,
  "approved_at" timestamptz NULL,
  "delete_status" boolean NOT NULL DEFAULT false,
  "created_at" timestamptz NOT NULL,
  "updated_at" timestamptz NOT NULL,
  PRIMARY KEY ("id")
);
CREATE INDEX "consultantvoucher_tenant_id" ON "consultant_vouchers" ("tenant_id");
CREATE INDEX "consultantvoucher_tenant_id_status" ON "consultant_vouchers" ("tenant_id", "status");
CREATE INDEX "consultantvoucher_tenant_id_employee_id" ON "consultant_vouchers" ("tenant_id", "employee_id");
