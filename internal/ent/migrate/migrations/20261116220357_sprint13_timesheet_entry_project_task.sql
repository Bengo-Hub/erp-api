-- Entries were unique per date, so a second project on the same day overwrote the first. They are
-- now unique per (date, project, task); production drops the old index in cmd/migrate before
-- Schema.Create (the online diff never drops indexes).
-- Drop index "timesheetentry_tenant_id_timesheet_id_date" from table: "timesheet_entries"
DROP INDEX "timesheetentry_tenant_id_timesheet_id_date";
-- Modify "timesheet_entries" table
ALTER TABLE "timesheet_entries" ADD COLUMN "task_id" uuid NULL, ADD COLUMN "billable" boolean NOT NULL DEFAULT false;
-- Create index "timesheetentry_tenant_id_timesheet_id_date_project_id_task_id" to table: "timesheet_entries"
CREATE UNIQUE INDEX "timesheetentry_tenant_id_timesheet_id_date_project_id_task_id" ON "timesheet_entries" ("tenant_id", "timesheet_id", "date", "project_id", "task_id");
