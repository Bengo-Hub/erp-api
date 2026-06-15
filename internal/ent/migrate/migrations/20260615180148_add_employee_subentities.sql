-- Create "employee_disciplinaries" table
CREATE TABLE "employee_disciplinaries" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "incident_date" timestamptz NULL, "category" character varying NULL, "description" text NULL, "action_taken" character varying NULL, "status" character varying NOT NULL DEFAULT 'open', "document_url" character varying NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "employeedisciplinary_employee_id" to table: "employee_disciplinaries"
CREATE INDEX "employeedisciplinary_employee_id" ON "employee_disciplinaries" ("employee_id");
-- Create index "employeedisciplinary_tenant_id" to table: "employee_disciplinaries"
CREATE INDEX "employeedisciplinary_tenant_id" ON "employee_disciplinaries" ("tenant_id");
-- Create "employee_educations" table
CREATE TABLE "employee_educations" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "institution" character varying NOT NULL, "qualification" character varying NULL, "field_of_study" character varying NULL, "grade" character varying NULL, "start_date" timestamptz NULL, "end_date" timestamptz NULL, "certificate_url" character varying NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "employeeeducation_employee_id" to table: "employee_educations"
CREATE INDEX "employeeeducation_employee_id" ON "employee_educations" ("employee_id");
-- Create index "employeeeducation_tenant_id" to table: "employee_educations"
CREATE INDEX "employeeeducation_tenant_id" ON "employee_educations" ("tenant_id");
-- Create "employment_histories" table
CREATE TABLE "employment_histories" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "employer" character varying NOT NULL, "designation" character varying NULL, "start_date" timestamptz NULL, "end_date" timestamptz NULL, "reason_for_leaving" character varying NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "employmenthistory_employee_id" to table: "employment_histories"
CREATE INDEX "employmenthistory_employee_id" ON "employment_histories" ("employee_id");
-- Create index "employmenthistory_tenant_id" to table: "employment_histories"
CREATE INDEX "employmenthistory_tenant_id" ON "employment_histories" ("tenant_id");
