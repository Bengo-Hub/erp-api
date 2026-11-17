-- Timesheet entries carry billing_ref and billed_invoice_id while projects-api bills them. The SQL
-- default lets the online migration add the NOT NULL column to existing rows.
-- Modify "timesheet_entries" table
ALTER TABLE "timesheet_entries" ADD COLUMN "metadata" jsonb NOT NULL DEFAULT '{}';
