-- Create "payslip_lines" table
CREATE TABLE "payslip_lines" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "payslip_id" uuid NOT NULL, "component_id" uuid NULL, "section" character varying NOT NULL, "code" character varying NULL, "label" character varying NOT NULL, "cash_amount" numeric(18,4) NOT NULL, "taxable_amount" numeric(18,4) NOT NULL, "employer_amount" numeric(18,4) NOT NULL, "non_cash" boolean NOT NULL DEFAULT false, "taxable" boolean NOT NULL DEFAULT true, "quantity" numeric(7,2) NOT NULL, "rate" numeric(18,4) NOT NULL, "unit" character varying NULL, "deduction_phase" character varying NULL, "sort_order" bigint NOT NULL DEFAULT 0, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "payslipline_payslip_id" to table: "payslip_lines"
CREATE INDEX "payslipline_payslip_id" ON "payslip_lines" ("payslip_id");
-- Create index "payslipline_tenant_id" to table: "payslip_lines"
CREATE INDEX "payslipline_tenant_id" ON "payslip_lines" ("tenant_id");
-- Create index "payslipline_tenant_id_section" to table: "payslip_lines"
CREATE INDEX "payslipline_tenant_id_section" ON "payslip_lines" ("tenant_id", "section");
