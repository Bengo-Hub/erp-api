-- Modify "attendance_records" table
ALTER TABLE "attendance_records" ADD COLUMN "metadata" jsonb NULL;
-- Modify "casual_payments" table
ALTER TABLE "casual_payments" ALTER COLUMN "task_description" TYPE text;
-- Modify "employees" table
ALTER TABLE "employees" ADD COLUMN "device_pin" character varying NULL, ADD COLUMN "metadata" jsonb NULL;
-- Create index "employee_tenant_id_device_pin" to table: "employees"
CREATE UNIQUE INDEX "employee_tenant_id_device_pin" ON "employees" ("tenant_id", "device_pin");
-- Modify "general_hr_settings" table
ALTER TABLE "general_hr_settings" ADD COLUMN "paye_enabled" boolean NOT NULL DEFAULT true, ADD COLUMN "nssf_enabled" boolean NOT NULL DEFAULT true, ADD COLUMN "shif_enabled" boolean NOT NULL DEFAULT true, ADD COLUMN "housing_levy_enabled" boolean NOT NULL DEFAULT true, ADD COLUMN "nita_enabled" boolean NOT NULL DEFAULT true;
-- Modify "recovery_lines" table
ALTER TABLE "recovery_lines" ALTER COLUMN "amount" DROP DEFAULT;
-- Modify "staff_purchase_deductions" table
ALTER TABLE "staff_purchase_deductions" ALTER COLUMN "principal" DROP DEFAULT, ALTER COLUMN "amount_recovered" DROP DEFAULT, ALTER COLUMN "installment_amount" DROP DEFAULT;
-- Create "access_events" table
CREATE TABLE "access_events" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "device_id" uuid NOT NULL, "device_sn" character varying NOT NULL, "device_pin" character varying NOT NULL DEFAULT '', "employee_id" uuid NULL, "occurred_at" timestamptz NOT NULL, "door" bigint NOT NULL DEFAULT 1, "result" character varying NOT NULL, "event_code" bigint NOT NULL DEFAULT 0, "verify_mode" bigint NOT NULL DEFAULT 0, "in_out" bigint NOT NULL DEFAULT 0, "metadata" jsonb NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "accessevent_device_sn_device_pin_occurred_at_door_event_code" to table: "access_events"
CREATE UNIQUE INDEX "accessevent_device_sn_device_pin_occurred_at_door_event_code" ON "access_events" ("device_sn", "device_pin", "occurred_at", "door", "event_code");
-- Create index "accessevent_tenant_id_occurred_at" to table: "access_events"
CREATE INDEX "accessevent_tenant_id_occurred_at" ON "access_events" ("tenant_id", "occurred_at");
-- Create index "accessevent_tenant_id_result" to table: "access_events"
CREATE INDEX "accessevent_tenant_id_result" ON "access_events" ("tenant_id", "result");
-- Create "attendance_devices" table
CREATE TABLE "attendance_devices" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "outlet_id" uuid NULL, "work_site_id" uuid NULL, "serial_number" character varying NOT NULL, "name" character varying NOT NULL, "mode" character varying NOT NULL DEFAULT 'ta', "active" boolean NOT NULL DEFAULT true, "timezone" character varying NULL, "last_seen_at" timestamptz NULL, "firmware" character varying NULL, "push_version" character varying NULL, "last_ip" character varying NULL, "user_count" bigint NOT NULL DEFAULT 0, "punch_count" bigint NOT NULL DEFAULT 0, "metadata" jsonb NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "attendancedevice_serial_number" to table: "attendance_devices"
CREATE UNIQUE INDEX "attendancedevice_serial_number" ON "attendance_devices" ("serial_number");
-- Create index "attendancedevice_tenant_id" to table: "attendance_devices"
CREATE INDEX "attendancedevice_tenant_id" ON "attendance_devices" ("tenant_id");
-- Create "attendance_punches" table
CREATE TABLE "attendance_punches" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "device_id" uuid NULL, "device_sn" character varying NOT NULL DEFAULT '', "device_pin" character varying NOT NULL, "employee_id" uuid NULL, "punched_at" timestamptz NOT NULL, "status" bigint NOT NULL DEFAULT 0, "verify_mode" bigint NOT NULL DEFAULT 0, "work_code" character varying NULL, "source" character varying NOT NULL DEFAULT 'device', "processed" boolean NOT NULL DEFAULT false, "attendance_record_id" uuid NULL, "flagged" boolean NOT NULL DEFAULT false, "metadata" jsonb NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "attendancepunch_device_sn_device_pin_punched_at" to table: "attendance_punches"
CREATE UNIQUE INDEX "attendancepunch_device_sn_device_pin_punched_at" ON "attendance_punches" ("device_sn", "device_pin", "punched_at");
-- Create index "attendancepunch_tenant_id_employee_id_punched_at" to table: "attendance_punches"
CREATE INDEX "attendancepunch_tenant_id_employee_id_punched_at" ON "attendance_punches" ("tenant_id", "employee_id", "punched_at");
-- Create index "attendancepunch_tenant_id_processed" to table: "attendance_punches"
CREATE INDEX "attendancepunch_tenant_id_processed" ON "attendance_punches" ("tenant_id", "processed");
-- Create index "attendancepunch_tenant_id_punched_at" to table: "attendance_punches"
CREATE INDEX "attendancepunch_tenant_id_punched_at" ON "attendance_punches" ("tenant_id", "punched_at");
-- Create "device_commands" table
CREATE TABLE "device_commands" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "device_id" uuid NOT NULL, "cmd_no" bigint NOT NULL, "command_type" character varying NOT NULL, "command" text NOT NULL, "status" character varying NOT NULL DEFAULT 'queued', "return_code" bigint NULL, "result" text NULL, "created_by" uuid NULL, "sent_at" timestamptz NULL, "completed_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "devicecommand_device_id_cmd_no" to table: "device_commands"
CREATE UNIQUE INDEX "devicecommand_device_id_cmd_no" ON "device_commands" ("device_id", "cmd_no");
-- Create index "devicecommand_device_id_status" to table: "device_commands"
CREATE INDEX "devicecommand_device_id_status" ON "device_commands" ("device_id", "status");
-- Create index "devicecommand_tenant_id" to table: "device_commands"
CREATE INDEX "devicecommand_tenant_id" ON "device_commands" ("tenant_id");
-- Create "mileage_routes" table
CREATE TABLE "mileage_routes" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "expense_claim_id" uuid NOT NULL, "route_date" timestamptz NULL, "from_location" character varying NULL, "to_location" character varying NULL, "distance" numeric(10,2) NOT NULL, "rate" numeric(10,4) NOT NULL, "amount" numeric(18,4) NOT NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "mileageroute_expense_claim_id" to table: "mileage_routes"
CREATE INDEX "mileageroute_expense_claim_id" ON "mileage_routes" ("expense_claim_id");
-- Create index "mileageroute_tenant_id" to table: "mileage_routes"
CREATE INDEX "mileageroute_tenant_id" ON "mileage_routes" ("tenant_id");
-- Create "work_sites" table
CREATE TABLE "work_sites" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "outlet_id" uuid NULL, "name" character varying NOT NULL, "center_lat" double precision NOT NULL DEFAULT 0, "center_lng" double precision NOT NULL DEFAULT 0, "radius_m" double precision NOT NULL DEFAULT 100, "ring" jsonb NULL, "holes" jsonb NULL, "active" boolean NOT NULL DEFAULT true, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "worksite_tenant_id" to table: "work_sites"
CREATE INDEX "worksite_tenant_id" ON "work_sites" ("tenant_id");
-- Create index "worksite_tenant_id_active" to table: "work_sites"
CREATE INDEX "worksite_tenant_id_active" ON "work_sites" ("tenant_id", "active");
