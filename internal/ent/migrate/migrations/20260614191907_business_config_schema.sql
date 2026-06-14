-- Create "company_settings" table
CREATE TABLE "company_settings" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "legal_name" character varying NULL, "kra_pin" character varying NULL, "nssf_employer_no" character varying NULL, "shif_employer_no" character varying NULL, "contact_email" character varying NULL, "contact_phone" character varying NULL, "postal_address" character varying NULL, "physical_address" character varying NULL, "financial_year_start_month" bigint NOT NULL DEFAULT 1, "default_currency" character varying NOT NULL DEFAULT 'KES', "timezone" character varying NOT NULL DEFAULT 'Africa/Nairobi', "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "company_settings_tenant_id_key" to table: "company_settings"
CREATE UNIQUE INDEX "company_settings_tenant_id_key" ON "company_settings" ("tenant_id");
-- Create index "companysettings_tenant_id" to table: "company_settings"
CREATE UNIQUE INDEX "companysettings_tenant_id" ON "company_settings" ("tenant_id");
-- Create "document_sequences" table
CREATE TABLE "document_sequences" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "doc_type" character varying NOT NULL, "prefix" character varying NULL, "separator" character varying NOT NULL DEFAULT '-', "date_format" character varying NULL, "padding" bigint NOT NULL DEFAULT 6, "reset_freq" character varying NOT NULL DEFAULT 'never', "current_val" bigint NOT NULL DEFAULT 0, "last_reset" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "documentsequence_tenant_id_doc_type" to table: "document_sequences"
CREATE UNIQUE INDEX "documentsequence_tenant_id_doc_type" ON "document_sequences" ("tenant_id", "doc_type");
