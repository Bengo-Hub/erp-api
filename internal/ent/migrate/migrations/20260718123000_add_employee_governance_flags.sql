-- Modify "employees" table: add governance flags (director / shareholder). Defaults keep the
-- change safe on populated tables — most staff are neither.
ALTER TABLE "employees" ADD COLUMN "is_director" boolean NOT NULL DEFAULT false, ADD COLUMN "is_shareholder" boolean NOT NULL DEFAULT false;
-- Modify "contracts" table: add the editable rich-text (HTML) body of the employment terms.
ALTER TABLE "contracts" ADD COLUMN "terms_html" text NULL;
