-- Modify "hr_details" table
ALTER TABLE "hr_details" DROP COLUMN "project_id";
-- Create "approval_requests" table
CREATE TABLE "approval_requests" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "module" character varying NOT NULL, "object_id" uuid NOT NULL, "object_reference" character varying NULL, "workflow_id" uuid NULL, "requester_employee_id" uuid NULL, "status" character varying NOT NULL DEFAULT 'pending', "current_sequence" bigint NOT NULL DEFAULT 1, "submitted_by" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, "decided_at" timestamptz NULL, PRIMARY KEY ("id"));
-- Create index "approvalrequest_tenant_id_module_object_id" to table: "approval_requests"
CREATE INDEX "approvalrequest_tenant_id_module_object_id" ON "approval_requests" ("tenant_id", "module", "object_id");
-- Create index "approvalrequest_tenant_id_status" to table: "approval_requests"
CREATE INDEX "approvalrequest_tenant_id_status" ON "approval_requests" ("tenant_id", "status");
-- Create "approval_step_actions" table
CREATE TABLE "approval_step_actions" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "sequence" bigint NOT NULL, "name" character varying NULL, "approver_type" character varying NOT NULL DEFAULT 'role', "approver_role" character varying NULL, "approver_employee_id" uuid NULL, "status" character varying NOT NULL DEFAULT 'pending', "acted_by" uuid NULL, "acted_at" timestamptz NULL, "comment" text NULL, "created_at" timestamptz NOT NULL, "request_id" uuid NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "approval_step_actions_approval_requests_actions" FOREIGN KEY ("request_id") REFERENCES "approval_requests" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION);
-- Create index "approvalstepaction_request_id_sequence" to table: "approval_step_actions"
CREATE INDEX "approvalstepaction_request_id_sequence" ON "approval_step_actions" ("request_id", "sequence");
-- Create index "approvalstepaction_tenant_id" to table: "approval_step_actions"
CREATE INDEX "approvalstepaction_tenant_id" ON "approval_step_actions" ("tenant_id");
-- Create "approval_workflows" table
CREATE TABLE "approval_workflows" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "module" character varying NOT NULL, "name" character varying NOT NULL, "description" character varying NULL, "is_active" boolean NOT NULL DEFAULT true, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "approvalworkflow_tenant_id_module_is_active" to table: "approval_workflows"
CREATE INDEX "approvalworkflow_tenant_id_module_is_active" ON "approval_workflows" ("tenant_id", "module", "is_active");
-- Create "approval_workflow_steps" table
CREATE TABLE "approval_workflow_steps" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "sequence" bigint NOT NULL, "name" character varying NOT NULL, "approver_type" character varying NOT NULL DEFAULT 'role', "approver_role" character varying NULL, "approver_employee_id" uuid NULL, "is_optional" boolean NOT NULL DEFAULT false, "created_at" timestamptz NOT NULL, "workflow_id" uuid NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "approval_workflow_steps_approval_workflows_steps" FOREIGN KEY ("workflow_id") REFERENCES "approval_workflows" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION);
-- Create index "approvalworkflowstep_tenant_id" to table: "approval_workflow_steps"
CREATE INDEX "approvalworkflowstep_tenant_id" ON "approval_workflow_steps" ("tenant_id");
-- Create index "approvalworkflowstep_workflow_id_sequence" to table: "approval_workflow_steps"
CREATE UNIQUE INDEX "approvalworkflowstep_workflow_id_sequence" ON "approval_workflow_steps" ("workflow_id", "sequence");
-- Create "tasks" table
CREATE TABLE "tasks" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "title" character varying NOT NULL, "description" text NULL, "status" character varying NOT NULL DEFAULT 'todo', "priority" character varying NOT NULL DEFAULT 'medium', "assignee_employee_id" uuid NULL, "created_by" uuid NULL, "category" character varying NULL, "progress" bigint NOT NULL DEFAULT 0, "due_date" timestamptz NULL, "completed_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "task_tenant_id" to table: "tasks"
CREATE INDEX "task_tenant_id" ON "tasks" ("tenant_id");
-- Create index "task_tenant_id_assignee_employee_id" to table: "tasks"
CREATE INDEX "task_tenant_id_assignee_employee_id" ON "tasks" ("tenant_id", "assignee_employee_id");
-- Create index "task_tenant_id_status" to table: "tasks"
CREATE INDEX "task_tenant_id_status" ON "tasks" ("tenant_id", "status");
-- Create "task_comments" table
CREATE TABLE "task_comments" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "author_user_id" uuid NULL, "body" text NOT NULL, "created_at" timestamptz NOT NULL, "task_id" uuid NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "task_comments_tasks_comments" FOREIGN KEY ("task_id") REFERENCES "tasks" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION);
-- Create index "taskcomment_task_id" to table: "task_comments"
CREATE INDEX "taskcomment_task_id" ON "task_comments" ("task_id");
-- Create index "taskcomment_tenant_id" to table: "task_comments"
CREATE INDEX "taskcomment_tenant_id" ON "task_comments" ("tenant_id");
-- Create "task_logs" table
CREATE TABLE "task_logs" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "action" character varying NOT NULL, "description" character varying NULL, "user_id" uuid NULL, "created_at" timestamptz NOT NULL, "task_id" uuid NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "task_logs_tasks_logs" FOREIGN KEY ("task_id") REFERENCES "tasks" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION);
-- Create index "tasklog_task_id" to table: "task_logs"
CREATE INDEX "tasklog_task_id" ON "task_logs" ("task_id");
-- Create index "tasklog_tenant_id" to table: "task_logs"
CREATE INDEX "tasklog_tenant_id" ON "task_logs" ("tenant_id");
