-- Create "applications" table
CREATE TABLE "applications" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "job_id" uuid NOT NULL, "candidate_id" uuid NOT NULL, "status" character varying NOT NULL DEFAULT 'applied', "applied_at" timestamptz NOT NULL, "notes" character varying NULL, "hired_employee_id" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "application_tenant_id" to table: "applications"
CREATE INDEX "application_tenant_id" ON "applications" ("tenant_id");
-- Create index "application_tenant_id_candidate_id" to table: "applications"
CREATE INDEX "application_tenant_id_candidate_id" ON "applications" ("tenant_id", "candidate_id");
-- Create index "application_tenant_id_job_id_status" to table: "applications"
CREATE INDEX "application_tenant_id_job_id_status" ON "applications" ("tenant_id", "job_id", "status");
-- Create "appraisals" table
CREATE TABLE "appraisals" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "cycle_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "evaluator_id" uuid NULL, "template_id" uuid NULL, "status" character varying NOT NULL DEFAULT 'draft', "overall_rating" numeric(3,1) NULL, "comments" character varying NULL, "rejection_reason" character varying NULL, "approved_at" timestamptz NULL, "rejected_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "appraisal_tenant_id" to table: "appraisals"
CREATE INDEX "appraisal_tenant_id" ON "appraisals" ("tenant_id");
-- Create index "appraisal_tenant_id_cycle_id" to table: "appraisals"
CREATE INDEX "appraisal_tenant_id_cycle_id" ON "appraisals" ("tenant_id", "cycle_id");
-- Create index "appraisal_tenant_id_employee_id" to table: "appraisals"
CREATE INDEX "appraisal_tenant_id_employee_id" ON "appraisals" ("tenant_id", "employee_id");
-- Create "appraisal_cycles" table
CREATE TABLE "appraisal_cycles" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "name" character varying NOT NULL, "description" character varying NULL, "start_date" timestamptz NOT NULL, "end_date" timestamptz NOT NULL, "due_date" timestamptz NULL, "status" character varying NOT NULL DEFAULT 'created', "created_by" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "appraisalcycle_tenant_id" to table: "appraisal_cycles"
CREATE INDEX "appraisalcycle_tenant_id" ON "appraisal_cycles" ("tenant_id");
-- Create index "appraisalcycle_tenant_id_status" to table: "appraisal_cycles"
CREATE INDEX "appraisalcycle_tenant_id_status" ON "appraisal_cycles" ("tenant_id", "status");
-- Create "appraisal_questions" table
CREATE TABLE "appraisal_questions" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "template_id" uuid NOT NULL, "question_text" character varying NOT NULL, "question_type" character varying NOT NULL, "is_required" boolean NOT NULL DEFAULT true, "order" bigint NOT NULL DEFAULT 0, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "appraisalquestion_tenant_id" to table: "appraisal_questions"
CREATE INDEX "appraisalquestion_tenant_id" ON "appraisal_questions" ("tenant_id");
-- Create index "appraisalquestion_tenant_id_template_id" to table: "appraisal_questions"
CREATE INDEX "appraisalquestion_tenant_id_template_id" ON "appraisal_questions" ("tenant_id", "template_id");
-- Create "appraisal_responses" table
CREATE TABLE "appraisal_responses" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "appraisal_id" uuid NOT NULL, "question_id" uuid NOT NULL, "response" character varying NULL, "rating" numeric(3,1) NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "appraisalresponse_tenant_id" to table: "appraisal_responses"
CREATE INDEX "appraisalresponse_tenant_id" ON "appraisal_responses" ("tenant_id");
-- Create index "appraisalresponse_tenant_id_appraisal_id" to table: "appraisal_responses"
CREATE INDEX "appraisalresponse_tenant_id_appraisal_id" ON "appraisal_responses" ("tenant_id", "appraisal_id");
-- Create "appraisal_templates" table
CREATE TABLE "appraisal_templates" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "name" character varying NOT NULL, "description" character varying NULL, "is_active" boolean NOT NULL DEFAULT true, "created_by" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "appraisaltemplate_tenant_id" to table: "appraisal_templates"
CREATE INDEX "appraisaltemplate_tenant_id" ON "appraisal_templates" ("tenant_id");
-- Create index "appraisaltemplate_tenant_id_is_active" to table: "appraisal_templates"
CREATE INDEX "appraisaltemplate_tenant_id_is_active" ON "appraisal_templates" ("tenant_id", "is_active");
-- Create "candidates" table
CREATE TABLE "candidates" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "full_name" character varying NOT NULL, "email" character varying NOT NULL, "phone" character varying NULL, "resume_url" character varying NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "candidate_tenant_id" to table: "candidates"
CREATE INDEX "candidate_tenant_id" ON "candidates" ("tenant_id");
-- Create index "candidate_tenant_id_email" to table: "candidates"
CREATE INDEX "candidate_tenant_id_email" ON "candidates" ("tenant_id", "email");
-- Create "employee_metrics" table
CREATE TABLE "employee_metrics" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "metric_id" uuid NOT NULL, "value" character varying NULL, "numeric_value" numeric(12,2) NULL, "date_recorded" timestamptz NOT NULL, "period_start" timestamptz NULL, "period_end" timestamptz NULL, "notes" character varying NULL, "recorded_by" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "employeemetric_tenant_id" to table: "employee_metrics"
CREATE INDEX "employeemetric_tenant_id" ON "employee_metrics" ("tenant_id");
-- Create index "employeemetric_tenant_id_employee_id_metric_id_date_recorded" to table: "employee_metrics"
CREATE UNIQUE INDEX "employeemetric_tenant_id_employee_id_metric_id_date_recorded" ON "employee_metrics" ("tenant_id", "employee_id", "metric_id", "date_recorded");
-- Create "employee_onboardings" table
CREATE TABLE "employee_onboardings" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "status" character varying NOT NULL DEFAULT 'not_started', "probation_end_date" timestamptz NULL, "started_at" timestamptz NULL, "completed_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "employeeonboarding_tenant_id" to table: "employee_onboardings"
CREATE INDEX "employeeonboarding_tenant_id" ON "employee_onboardings" ("tenant_id");
-- Create index "employeeonboarding_tenant_id_employee_id" to table: "employee_onboardings"
CREATE INDEX "employeeonboarding_tenant_id_employee_id" ON "employee_onboardings" ("tenant_id", "employee_id");
-- Create "goals" table
CREATE TABLE "goals" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "title" character varying NOT NULL, "description" character varying NULL, "start_date" timestamptz NULL, "end_date" timestamptz NULL, "status" character varying NOT NULL DEFAULT 'not_started', "progress" bigint NOT NULL DEFAULT 0, "is_template" boolean NOT NULL DEFAULT false, "created_by" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "goal_tenant_id" to table: "goals"
CREATE INDEX "goal_tenant_id" ON "goals" ("tenant_id");
-- Create index "goal_tenant_id_employee_id" to table: "goals"
CREATE INDEX "goal_tenant_id_employee_id" ON "goals" ("tenant_id", "employee_id");
-- Create "goal_progresses" table
CREATE TABLE "goal_progresses" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "goal_id" uuid NOT NULL, "progress" bigint NOT NULL, "comments" character varying NULL, "updated_by" uuid NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "goalprogress_tenant_id" to table: "goal_progresses"
CREATE INDEX "goalprogress_tenant_id" ON "goal_progresses" ("tenant_id");
-- Create index "goalprogress_tenant_id_goal_id" to table: "goal_progresses"
CREATE INDEX "goalprogress_tenant_id_goal_id" ON "goal_progresses" ("tenant_id", "goal_id");
-- Create "job_postings" table
CREATE TABLE "job_postings" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "title" character varying NOT NULL, "description" character varying NULL, "department" character varying NULL, "location" character varying NULL, "status" character varying NOT NULL DEFAULT 'draft', "posted_at" timestamptz NOT NULL, "closed_at" timestamptz NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "jobposting_tenant_id" to table: "job_postings"
CREATE INDEX "jobposting_tenant_id" ON "job_postings" ("tenant_id");
-- Create index "jobposting_tenant_id_status" to table: "job_postings"
CREATE INDEX "jobposting_tenant_id_status" ON "job_postings" ("tenant_id", "status");
-- Create "metric_categories" table
CREATE TABLE "metric_categories" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "name" character varying NOT NULL, "description" character varying NULL, "order" bigint NOT NULL DEFAULT 0, "is_active" boolean NOT NULL DEFAULT true, "created_by" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "metriccategory_tenant_id" to table: "metric_categories"
CREATE INDEX "metriccategory_tenant_id" ON "metric_categories" ("tenant_id");
-- Create index "metriccategory_tenant_id_is_active" to table: "metric_categories"
CREATE INDEX "metriccategory_tenant_id_is_active" ON "metric_categories" ("tenant_id", "is_active");
-- Create "metric_targets" table
CREATE TABLE "metric_targets" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "metric_id" uuid NOT NULL, "target_value" numeric(12,2) NOT NULL, "period_start" timestamptz NOT NULL, "period_end" timestamptz NOT NULL, "is_active" boolean NOT NULL DEFAULT true, "created_by" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "metrictarget_tenant_id" to table: "metric_targets"
CREATE INDEX "metrictarget_tenant_id" ON "metric_targets" ("tenant_id");
-- Create index "metrictarget_tenant_id_employe_ad0ee8fb086ede9d3e89660625da9d94" to table: "metric_targets"
CREATE UNIQUE INDEX "metrictarget_tenant_id_employe_ad0ee8fb086ede9d3e89660625da9d94" ON "metric_targets" ("tenant_id", "employee_id", "metric_id", "period_start", "period_end");
-- Create "onboarding_tasks" table
CREATE TABLE "onboarding_tasks" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "onboarding_id" uuid NOT NULL, "category" character varying NOT NULL DEFAULT 'Other', "title" character varying NOT NULL, "order" bigint NOT NULL DEFAULT 0, "is_done" boolean NOT NULL DEFAULT false, "done_at" timestamptz NULL, "assigned_to" uuid NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "onboardingtask_tenant_id" to table: "onboarding_tasks"
CREATE INDEX "onboardingtask_tenant_id" ON "onboarding_tasks" ("tenant_id");
-- Create index "onboardingtask_tenant_id_onboarding_id" to table: "onboarding_tasks"
CREATE INDEX "onboardingtask_tenant_id_onboarding_id" ON "onboarding_tasks" ("tenant_id", "onboarding_id");
-- Create "performance_metrics" table
CREATE TABLE "performance_metrics" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "category_id" uuid NOT NULL, "name" character varying NOT NULL, "description" character varying NULL, "metric_type" character varying NOT NULL, "unit" character varying NULL, "min_value" numeric(12,2) NULL, "max_value" numeric(12,2) NULL, "target_value" numeric(12,2) NULL, "is_active" boolean NOT NULL DEFAULT true, "created_by" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "performancemetric_tenant_id" to table: "performance_metrics"
CREATE INDEX "performancemetric_tenant_id" ON "performance_metrics" ("tenant_id");
-- Create index "performancemetric_tenant_id_category_id" to table: "performance_metrics"
CREATE INDEX "performancemetric_tenant_id_category_id" ON "performance_metrics" ("tenant_id", "category_id");
-- Create "performance_reviews" table
CREATE TABLE "performance_reviews" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "title" character varying NOT NULL, "description" character varying NULL, "review_date" timestamptz NOT NULL, "status" character varying NOT NULL DEFAULT 'draft', "overall_rating" numeric(3,1) NULL, "comments" character varying NULL, "reviewer_id" uuid NULL, "created_by" uuid NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "performancereview_tenant_id" to table: "performance_reviews"
CREATE INDEX "performancereview_tenant_id" ON "performance_reviews" ("tenant_id");
-- Create index "performancereview_tenant_id_employee_id" to table: "performance_reviews"
CREATE INDEX "performancereview_tenant_id_employee_id" ON "performance_reviews" ("tenant_id", "employee_id");
-- Create index "performancereview_tenant_id_status" to table: "performance_reviews"
CREATE INDEX "performancereview_tenant_id_status" ON "performance_reviews" ("tenant_id", "status");
-- Create "review_metrics" table
CREATE TABLE "review_metrics" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "review_id" uuid NOT NULL, "metric_id" uuid NOT NULL, "value" character varying NULL, "rating" numeric(3,1) NULL, "comments" character varying NULL, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "reviewmetric_tenant_id" to table: "review_metrics"
CREATE INDEX "reviewmetric_tenant_id" ON "review_metrics" ("tenant_id");
-- Create index "reviewmetric_tenant_id_review_id_metric_id" to table: "review_metrics"
CREATE UNIQUE INDEX "reviewmetric_tenant_id_review_id_metric_id" ON "review_metrics" ("tenant_id", "review_id", "metric_id");
-- Create "training_courses" table
CREATE TABLE "training_courses" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "title" character varying NOT NULL, "description" character varying NULL, "start_date" timestamptz NOT NULL, "end_date" timestamptz NOT NULL, "capacity" bigint NOT NULL DEFAULT 0, "created_at" timestamptz NOT NULL, "updated_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "trainingcourse_tenant_id" to table: "training_courses"
CREATE INDEX "trainingcourse_tenant_id" ON "training_courses" ("tenant_id");
-- Create index "trainingcourse_tenant_id_start_date" to table: "training_courses"
CREATE INDEX "trainingcourse_tenant_id_start_date" ON "training_courses" ("tenant_id", "start_date");
-- Create "training_enrollments" table
CREATE TABLE "training_enrollments" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "course_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "status" character varying NOT NULL DEFAULT 'enrolled', "enrolled_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "trainingenrollment_tenant_id" to table: "training_enrollments"
CREATE INDEX "trainingenrollment_tenant_id" ON "training_enrollments" ("tenant_id");
-- Create index "trainingenrollment_tenant_id_course_id_employee_id" to table: "training_enrollments"
CREATE UNIQUE INDEX "trainingenrollment_tenant_id_course_id_employee_id" ON "training_enrollments" ("tenant_id", "course_id", "employee_id");
-- Create index "trainingenrollment_tenant_id_course_id_status" to table: "training_enrollments"
CREATE INDEX "trainingenrollment_tenant_id_course_id_status" ON "training_enrollments" ("tenant_id", "course_id", "status");
-- Create "training_evaluations" table
CREATE TABLE "training_evaluations" ("id" uuid NOT NULL, "tenant_id" uuid NOT NULL, "course_id" uuid NOT NULL, "employee_id" uuid NOT NULL, "rating" bigint NOT NULL DEFAULT 0, "feedback" character varying NULL, "created_at" timestamptz NOT NULL, PRIMARY KEY ("id"));
-- Create index "trainingevaluation_tenant_id" to table: "training_evaluations"
CREATE INDEX "trainingevaluation_tenant_id" ON "training_evaluations" ("tenant_id");
-- Create index "trainingevaluation_tenant_id_course_id" to table: "training_evaluations"
CREATE INDEX "trainingevaluation_tenant_id_course_id" ON "training_evaluations" ("tenant_id", "course_id");
