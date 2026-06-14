-- Create "attendance_records" table
CREATE TABLE "attendance_records" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "outlet_id" uuid NULL, "employee_id" uuid NOT NULL, "work_shift_id" uuid NULL, "date" timestamptz NOT NULL, "check_in" timestamptz NULL, "check_out" timestamptz NULL, "biometric_id" character varying NULL, "gps_latitude" numeric(9,6) NULL, "gps_longitude" numeric(9,6) NULL, "status" character varying NOT NULL DEFAULT 'present', "total_seconds_worked" bigint NOT NULL DEFAULT 0, "regular_hours" numeric(8,2) NOT NULL, "overtime_hours" numeric(8,2) NOT NULL, "notes" character varying NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "attendancerecord_tenant_id" to table: "attendance_records"
CREATE INDEX "attendancerecord_tenant_id" ON "attendance_records" ("tenant_id");
-- Create index "attendancerecord_tenant_id_date" to table: "attendance_records"
CREATE INDEX "attendancerecord_tenant_id_date" ON "attendance_records" ("tenant_id", "date");
-- Create index "attendancerecord_tenant_id_employee_id_date" to table: "attendance_records"
CREATE UNIQUE INDEX "attendancerecord_tenant_id_employee_id_date" ON "attendance_records" ("tenant_id", "employee_id", "date");
-- Create index "attendancerecord_tenant_id_status" to table: "attendance_records"
CREATE INDEX "attendancerecord_tenant_id_status" ON "attendance_records" ("tenant_id", "status");
-- Create "attendance_rules" table
CREATE TABLE "attendance_rules" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "branch_id" uuid NULL, "department_id" uuid NULL, "name" character varying NOT NULL, "rule_type" character varying NOT NULL, "description" character varying NULL, "is_active" boolean NOT NULL DEFAULT true, "priority" bigint NOT NULL DEFAULT 100, "late_threshold_minutes" bigint NOT NULL DEFAULT 15, "late_penalty_type" character varying NOT NULL DEFAULT 'warning', "late_penalty_value" numeric(10,4) NOT NULL, "overtime_threshold_hours" numeric(10,4) NOT NULL, "overtime_rate_multiplier" numeric(10,4) NOT NULL, "max_overtime_hours" numeric(10,4) NOT NULL, "consecutive_absent_threshold" bigint NOT NULL DEFAULT 3, "monthly_absent_threshold" bigint NOT NULL DEFAULT 5, "absenteeism_action" character varying NOT NULL DEFAULT 'warning', "standard_work_hours" numeric(10,4) NOT NULL, "min_work_hours" numeric(10,4) NOT NULL, "max_work_hours" numeric(10,4) NOT NULL, "break_duration_minutes" bigint NOT NULL DEFAULT 60, "holiday_pay_multiplier" numeric(10,4) NOT NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "attendancerule_tenant_id" to table: "attendance_rules"
CREATE INDEX "attendancerule_tenant_id" ON "attendance_rules" ("tenant_id");
-- Create index "attendancerule_tenant_id_priority" to table: "attendance_rules"
CREATE INDEX "attendancerule_tenant_id_priority" ON "attendance_rules" ("tenant_id", "priority");
-- Create index "attendancerule_tenant_id_rule_type_is_active" to table: "attendance_rules"
CREATE INDEX "attendancerule_tenant_id_rule_type_is_active" ON "attendance_rules" ("tenant_id", "rule_type", "is_active");
-- Create "ess_settings" table
CREATE TABLE "ess_settings" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "enable_shift_based_restrictions" boolean NOT NULL DEFAULT true, "allow_payslip_view" boolean NOT NULL DEFAULT true, "allow_leave_application" boolean NOT NULL DEFAULT true, "allow_timesheet_application" boolean NOT NULL DEFAULT false, "allow_overtime_application" boolean NOT NULL DEFAULT false, "allow_advance_salary_application" boolean NOT NULL DEFAULT false, "allow_losses_damage_submission" boolean NOT NULL DEFAULT false, "allow_expense_claims_application" boolean NOT NULL DEFAULT false, "require_password_change_on_first_login" boolean NOT NULL DEFAULT true, "session_timeout_minutes" bigint NOT NULL DEFAULT 60, "allow_weekend_login" boolean NOT NULL DEFAULT false, "max_failed_login_attempts" bigint NOT NULL DEFAULT 5, "account_lockout_duration_minutes" bigint NOT NULL DEFAULT 30, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "ess_settings_tenant_id_key" to table: "ess_settings"
CREATE UNIQUE INDEX "ess_settings_tenant_id_key" ON "ess_settings" ("tenant_id");
-- Create index "esssettings_tenant_id" to table: "ess_settings"
CREATE UNIQUE INDEX "esssettings_tenant_id" ON "ess_settings" ("tenant_id");
-- Create "off_days" table
CREATE TABLE "off_days" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "date" timestamptz NOT NULL, "reason" character varying NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "offday_tenant_id" to table: "off_days"
CREATE INDEX "offday_tenant_id" ON "off_days" ("tenant_id");
-- Create index "offday_tenant_id_employee_id_date" to table: "off_days"
CREATE UNIQUE INDEX "offday_tenant_id_employee_id_date" ON "off_days" ("tenant_id", "employee_id", "date");
-- Create "shift_assignments" table
CREATE TABLE "shift_assignments" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "roster_id" uuid NOT NULL, "start_date" timestamptz NOT NULL, "end_date" timestamptz NULL, "is_active" boolean NOT NULL DEFAULT true, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "shiftassignment_tenant_id" to table: "shift_assignments"
CREATE INDEX "shiftassignment_tenant_id" ON "shift_assignments" ("tenant_id");
-- Create index "shiftassignment_tenant_id_employee_id_is_active" to table: "shift_assignments"
CREATE INDEX "shiftassignment_tenant_id_employee_id_is_active" ON "shift_assignments" ("tenant_id", "employee_id", "is_active");
-- Create index "shiftassignment_tenant_id_roster_id" to table: "shift_assignments"
CREATE INDEX "shiftassignment_tenant_id_roster_id" ON "shift_assignments" ("tenant_id", "roster_id");
-- Create "shift_rosters" table
CREATE TABLE "shift_rosters" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "outlet_id" uuid NULL, "name" character varying NOT NULL, "cycle_days" bigint NOT NULL DEFAULT 14, "start_date" timestamptz NOT NULL, "is_active" boolean NOT NULL DEFAULT true, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "shiftroster_tenant_id" to table: "shift_rosters"
CREATE INDEX "shiftroster_tenant_id" ON "shift_rosters" ("tenant_id");
-- Create index "shiftroster_tenant_id_is_active" to table: "shift_rosters"
CREATE INDEX "shiftroster_tenant_id_is_active" ON "shift_rosters" ("tenant_id", "is_active");
-- Create "shift_roster_slots" table
CREATE TABLE "shift_roster_slots" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "roster_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "cycle_day" bigint NOT NULL, "start_time" character varying NULL, "end_time" character varying NULL, "is_off_day" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "shiftrosterslot_tenant_id" to table: "shift_roster_slots"
CREATE INDEX "shiftrosterslot_tenant_id" ON "shift_roster_slots" ("tenant_id");
-- Create index "shiftrosterslot_tenant_id_roster_id_cycle_day" to table: "shift_roster_slots"
CREATE INDEX "shiftrosterslot_tenant_id_roster_id_cycle_day" ON "shift_roster_slots" ("tenant_id", "roster_id", "cycle_day");
-- Create index "shiftrosterslot_tenant_id_roster_id_employee_id_cycle_day" to table: "shift_roster_slots"
CREATE UNIQUE INDEX "shiftrosterslot_tenant_id_roster_id_employee_id_cycle_day" ON "shift_roster_slots" ("tenant_id", "roster_id", "employee_id", "cycle_day");
-- Create "shift_rotations" table
CREATE TABLE "shift_rotations" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "title" character varying NOT NULL, "shift_ids" jsonb NULL, "current_active_shift_id" uuid NULL, "last_shift_id" uuid NULL, "run_duration" bigint NOT NULL DEFAULT 2, "run_unit" character varying NOT NULL DEFAULT 'Months', "break_duration" bigint NOT NULL DEFAULT 1, "break_unit" character varying NOT NULL DEFAULT 'Day', "next_change_date" timestamptz NULL, "is_active" boolean NOT NULL DEFAULT true, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "shiftrotation_tenant_id" to table: "shift_rotations"
CREATE INDEX "shiftrotation_tenant_id" ON "shift_rotations" ("tenant_id");
-- Create index "shiftrotation_tenant_id_is_active" to table: "shift_rotations"
CREATE INDEX "shiftrotation_tenant_id_is_active" ON "shift_rotations" ("tenant_id", "is_active");
-- Create "staff_shift_overrides" table
CREATE TABLE "staff_shift_overrides" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "outlet_id" uuid NULL, "employee_id" uuid NOT NULL, "date" timestamptz NOT NULL, "override_type" character varying NOT NULL, "start_time" character varying NULL, "end_time" character varying NULL, "reason" character varying NULL, "status" character varying NOT NULL DEFAULT 'approved', "created_by" uuid NULL, "approved_by" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "staffshiftoverride_tenant_id" to table: "staff_shift_overrides"
CREATE INDEX "staffshiftoverride_tenant_id" ON "staff_shift_overrides" ("tenant_id");
-- Create index "staffshiftoverride_tenant_id_employee_id_date" to table: "staff_shift_overrides"
CREATE UNIQUE INDEX "staffshiftoverride_tenant_id_employee_id_date" ON "staff_shift_overrides" ("tenant_id", "employee_id", "date");
-- Create index "staffshiftoverride_tenant_id_status" to table: "staff_shift_overrides"
CREATE INDEX "staffshiftoverride_tenant_id_status" ON "staff_shift_overrides" ("tenant_id", "status");
-- Create "timesheets" table
CREATE TABLE "timesheets" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "approver_id" uuid NULL, "period_start" timestamptz NOT NULL, "period_end" timestamptz NOT NULL, "status" character varying NOT NULL DEFAULT 'draft', "submission_date" timestamptz NULL, "approval_date" timestamptz NULL, "rejection_reason" character varying NULL, "total_hours" numeric(8,2) NOT NULL, "total_overtime_hours" numeric(8,2) NOT NULL, "notes" character varying NULL, "is_active" boolean NOT NULL DEFAULT true, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "timesheet_tenant_id" to table: "timesheets"
CREATE INDEX "timesheet_tenant_id" ON "timesheets" ("tenant_id");
-- Create index "timesheet_tenant_id_employee_id" to table: "timesheets"
CREATE INDEX "timesheet_tenant_id_employee_id" ON "timesheets" ("tenant_id", "employee_id");
-- Create index "timesheet_tenant_id_employee_id_period_start_period_end" to table: "timesheets"
CREATE UNIQUE INDEX "timesheet_tenant_id_employee_id_period_start_period_end" ON "timesheets" ("tenant_id", "employee_id", "period_start", "period_end");
-- Create "timesheet_entries" table
CREATE TABLE "timesheet_entries" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "timesheet_id" uuid NOT NULL, "project_id" uuid NULL, "date" timestamptz NOT NULL, "task_description" character varying NULL, "regular_hours" numeric(8,2) NOT NULL, "overtime_hours" numeric(8,2) NOT NULL, "break_hours" numeric(8,2) NOT NULL, "notes" character varying NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "timesheetentry_tenant_id" to table: "timesheet_entries"
CREATE INDEX "timesheetentry_tenant_id" ON "timesheet_entries" ("tenant_id");
-- Create index "timesheetentry_tenant_id_timesheet_id_date" to table: "timesheet_entries"
CREATE UNIQUE INDEX "timesheetentry_tenant_id_timesheet_id_date" ON "timesheet_entries" ("tenant_id", "timesheet_id", "date");
-- Create "work_shifts" table
CREATE TABLE "work_shifts" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "outlet_id" uuid NULL, "name" character varying NOT NULL, "start_time" character varying NULL, "end_time" character varying NULL, "grace_minutes" bigint NOT NULL DEFAULT 0, "total_hours_per_week" numeric(10,4) NOT NULL, "is_default" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "workshift_tenant_id" to table: "work_shifts"
CREATE INDEX "workshift_tenant_id" ON "work_shifts" ("tenant_id");
-- Create index "workshift_tenant_id_name" to table: "work_shifts"
CREATE INDEX "workshift_tenant_id_name" ON "work_shifts" ("tenant_id", "name");
-- Create "work_shift_schedules" table
CREATE TABLE "work_shift_schedules" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "work_shift_id" uuid NOT NULL, "day" character varying NOT NULL, "start_time" character varying NOT NULL, "end_time" character varying NOT NULL, "break_hours" numeric(10,4) NOT NULL, "is_working_day" boolean NOT NULL DEFAULT true, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "workshiftschedule_tenant_id" to table: "work_shift_schedules"
CREATE INDEX "workshiftschedule_tenant_id" ON "work_shift_schedules" ("tenant_id");
-- Create index "workshiftschedule_tenant_id_work_shift_id_day" to table: "work_shift_schedules"
CREATE UNIQUE INDEX "workshiftschedule_tenant_id_work_shift_id_day" ON "work_shift_schedules" ("tenant_id", "work_shift_id", "day");
