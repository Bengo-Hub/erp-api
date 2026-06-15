-- Drop index "exchangerate_base_currency_quote_currency_rate_date" from table: "exchange_rates"
DROP INDEX "exchangerate_base_currency_quote_currency_rate_date";
-- Create index "exchangerate_tenant_id_base_currency_quote_currency_rate_date" to table: "exchange_rates"
CREATE UNIQUE INDEX "exchangerate_tenant_id_base_currency_quote_currency_rate_date" ON "exchange_rates" ("tenant_id", "base_currency", "quote_currency", "rate_date");
