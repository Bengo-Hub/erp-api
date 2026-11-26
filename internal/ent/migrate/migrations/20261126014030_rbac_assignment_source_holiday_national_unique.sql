-- Create index "publicholiday_tenant_national_date" to table: "public_holidays"
CREATE UNIQUE INDEX "publicholiday_tenant_national_date" ON "public_holidays" ("tenant_id", "date") WHERE (is_national = true);
-- Modify "user_role_assignments" table
ALTER TABLE "user_role_assignments" ADD COLUMN "source" character varying NOT NULL DEFAULT 'sync';
