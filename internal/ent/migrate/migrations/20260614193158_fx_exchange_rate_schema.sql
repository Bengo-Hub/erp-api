-- Create "exchange_rates" table
CREATE TABLE "exchange_rates" ("id" uuid NOT NULL, "tenant_id" uuid NULL, "base_currency" character varying NOT NULL DEFAULT 'KES', "quote_currency" character varying NOT NULL, "rate" numeric(18,4) NOT NULL, "rate_date" timestamptz NOT NULL, "source" character varying NOT NULL DEFAULT 'exchangerate-api', "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "exchangerate_base_currency_quote_currency_rate_date" to table: "exchange_rates"
CREATE UNIQUE INDEX "exchangerate_base_currency_quote_currency_rate_date" ON "exchange_rates" ("base_currency", "quote_currency", "rate_date");
-- Create index "exchangerate_tenant_id" to table: "exchange_rates"
CREATE INDEX "exchangerate_tenant_id" ON "exchange_rates" ("tenant_id");
-- Create "exchange_rate_api_settings" table
CREATE TABLE "exchange_rate_api_settings" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "provider" character varying NOT NULL DEFAULT 'exchangerate-api', "api_key_ref" character varying NULL, "base_currency" character varying NOT NULL DEFAULT 'KES', "is_active" boolean NOT NULL DEFAULT false, "last_fetched_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "exchange_rate_api_settings_tenant_id_key" to table: "exchange_rate_api_settings"
CREATE UNIQUE INDEX "exchange_rate_api_settings_tenant_id_key" ON "exchange_rate_api_settings" ("tenant_id");
-- Create index "exchangerateapisettings_tenant_id" to table: "exchange_rate_api_settings"
CREATE UNIQUE INDEX "exchangerateapisettings_tenant_id" ON "exchange_rate_api_settings" ("tenant_id");
