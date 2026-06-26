-- Modify "company_settings" table
ALTER TABLE "company_settings" ADD COLUMN "date_format" character varying NOT NULL DEFAULT 'DD/MM/YYYY', ADD COLUMN "time_format" character varying NOT NULL DEFAULT 'HH:mm';
