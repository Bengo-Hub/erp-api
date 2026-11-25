package handlers

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/appraisals"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
	"github.com/Bengo-Hub/erp-api/internal/modules/performance"
	"github.com/Bengo-Hub/erp-api/internal/modules/recruitment"
	"github.com/Bengo-Hub/erp-api/internal/modules/tasks"
	"github.com/Bengo-Hub/erp-api/internal/modules/training"
	"github.com/Bengo-Hub/erp-api/internal/platform/tenantref"
)

// A tenant can never attach its records to another tenant's employee, candidate, posting, course,
// metric and so on by sending that record's id.
func TestIntegration_BodyIDsMustBelongToTenant(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	a, b := uuid.New(), uuid.New()
	day := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)

	ownEmp := client.Employee.Create().SetTenantID(a).SetFirstName("Own").SaveX(ctx)
	theirEmp := client.Employee.Create().SetTenantID(b).SetFirstName("Theirs").SaveX(ctx)
	theirCand := client.Candidate.Create().SetTenantID(b).SetFullName("Theirs Person").SetEmail("x@example.com").SaveX(ctx)
	ownCand := client.Candidate.Create().SetTenantID(a).SetFullName("Own Person").SetEmail("y@example.com").SaveX(ctx)
	ownJob := client.JobPosting.Create().SetTenantID(a).SetTitle("J").SaveX(ctx)
	theirJob := client.JobPosting.Create().SetTenantID(b).SetTitle("J").SaveX(ctx)
	ownCycle := client.AppraisalCycle.Create().SetTenantID(a).SetName("C").SetStartDate(day).SetEndDate(day).SetDueDate(day).SaveX(ctx)
	theirCycle := client.AppraisalCycle.Create().SetTenantID(b).SetName("C").SetStartDate(day).SetEndDate(day).SetDueDate(day).SaveX(ctx)
	theirTpl := client.AppraisalTemplate.Create().SetTenantID(b).SetName("T").SaveX(ctx)
	ownCourse := client.TrainingCourse.Create().SetTenantID(a).SetTitle("T").SetStartDate(day).SetEndDate(day).SaveX(ctx)
	ownCat := client.MetricCategory.Create().SetTenantID(a).SetName("C").SaveX(ctx)
	theirCat := client.MetricCategory.Create().SetTenantID(b).SetName("C").SaveX(ctx)
	ownMetric := client.PerformanceMetric.Create().SetTenantID(a).SetCategoryID(ownCat.ID).SetName("M").SetMetricType("numeric").SaveX(ctx)
	theirMetric := client.PerformanceMetric.Create().SetTenantID(b).SetCategoryID(theirCat.ID).SetName("M").SetMetricType("numeric").SaveX(ctx)
	ownReview := client.PerformanceReview.Create().SetTenantID(a).SetEmployeeID(ownEmp.ID).SetTitle("R").SetReviewDate(day).SaveX(ctx)
	theirReview := client.PerformanceReview.Create().SetTenantID(b).SetEmployeeID(theirEmp.ID).SetTitle("R").SetReviewDate(day).SaveX(ctx)
	theirDept := client.Department.Create().SetTenantID(b).SetTitle("D").SaveX(ctx)
	theirTitle := client.JobTitle.Create().SetTenantID(b).SetTitle("JT").SaveX(ctx)
	theirAdvance := client.Advance.Create().SetTenantID(b).SetEmployeeID(theirEmp.ID).SetAmountIssued(decimal.NewFromInt(1)).SaveX(ctx)

	rec, app, tr, perf := recruitment.NewService(client), appraisals.NewService(client), training.NewService(client), performance.NewService(client)
	pay, emps, tk := payroll.NewService(client, nil), employees.NewService(client), tasks.NewService(client)
	one := decimal.NewFromInt(1)

	refused := map[string]func() error{
		"application candidate": func() error { _, err := rec.CreateApplication(ctx, a, ownJob.ID, theirCand.ID, ""); return err },
		"application job":       func() error { _, err := rec.CreateApplication(ctx, a, theirJob.ID, ownCand.ID, ""); return err },
		"onboarding employee":   func() error { _, err := rec.StartOnboarding(ctx, a, theirEmp.ID); return err },
		"onboarding task list":  func() error { _, err := rec.AddTask(ctx, a, uuid.New(), "HR", "x"); return err },
		"appraisal employee": func() error {
			_, err := app.CreateAppraisal(ctx, a, appraisals.AppraisalInput{CycleID: ownCycle.ID, EmployeeID: theirEmp.ID})
			return err
		},
		"appraisal cycle": func() error {
			_, err := app.CreateAppraisal(ctx, a, appraisals.AppraisalInput{CycleID: theirCycle.ID, EmployeeID: ownEmp.ID})
			return err
		},
		"appraisal evaluator": func() error {
			_, err := app.CreateAppraisal(ctx, a, appraisals.AppraisalInput{CycleID: ownCycle.ID, EmployeeID: ownEmp.ID, EvaluatorID: &theirEmp.ID})
			return err
		},
		"appraisal template": func() error {
			_, err := app.CreateAppraisal(ctx, a, appraisals.AppraisalInput{CycleID: ownCycle.ID, EmployeeID: ownEmp.ID, TemplateID: &theirTpl.ID})
			return err
		},
		"question template": func() error {
			_, err := app.AddQuestion(ctx, a, appraisals.QuestionInput{TemplateID: theirTpl.ID, QuestionText: "q"})
			return err
		},
		"goal employee": func() error {
			_, err := app.CreateGoal(ctx, a, appraisals.GoalInput{EmployeeID: &theirEmp.ID, Title: "g"})
			return err
		},
		"enrolment employee": func() error { _, err := tr.Enroll(ctx, a, ownCourse.ID, theirEmp.ID); return err },
		"metric category": func() error {
			_, err := perf.CreateMetric(ctx, a, performance.MetricInput{CategoryID: theirCat.ID, Name: "m", MetricType: "numeric"})
			return err
		},
		"target employee": func() error { _, err := perf.SetTarget(ctx, a, theirEmp.ID, ownMetric.ID, one, day, day, nil); return err },
		"target metric":   func() error { _, err := perf.SetTarget(ctx, a, ownEmp.ID, theirMetric.ID, one, day, day, nil); return err },
		"recorded value employee": func() error {
			_, err := perf.RecordEmployeeMetric(ctx, a, performance.RecordMetricInput{EmployeeID: theirEmp.ID, MetricID: ownMetric.ID, Value: "1", DateRecorded: day})
			return err
		},
		"review employee": func() error {
			_, err := perf.CreateReview(ctx, a, performance.ReviewInput{EmployeeID: theirEmp.ID, Title: "r", ReviewDate: day})
			return err
		},
		"review reviewer": func() error {
			_, err := perf.CreateReview(ctx, a, performance.ReviewInput{EmployeeID: ownEmp.ID, ReviewerID: &theirEmp.ID, Title: "r", ReviewDate: day})
			return err
		},
		"review score review": func() error {
			_, err := perf.UpsertReviewMetric(ctx, a, performance.ReviewMetricInput{ReviewID: theirReview.ID, MetricID: ownMetric.ID, Value: "1"})
			return err
		},
		"review score metric": func() error {
			_, err := perf.UpsertReviewMetric(ctx, a, performance.ReviewMetricInput{ReviewID: ownReview.ID, MetricID: theirMetric.ID, Value: "1"})
			return err
		},
		"casual employee": func() error {
			_, err := pay.CreateCasualPayment(ctx, a, payroll.CasualPaymentInput{EmployeeID: &theirEmp.ID, Quantity: one, Rate: one})
			return err
		},
		"casual engager": func() error {
			_, err := pay.CreateCasualPayment(ctx, a, payroll.CasualPaymentInput{SettlementMode: "reimburse_engager", WorkerName: "w", EngagedByEmployeeID: &theirEmp.ID, Quantity: one, Rate: one})
			return err
		},
		"casual imprest": func() error {
			_, err := pay.CreateCasualPayment(ctx, a, payroll.CasualPaymentInput{EmployeeID: &ownEmp.ID, ImprestAdvanceID: &theirAdvance.ID, Quantity: one, Rate: one})
			return err
		},
		"consultant": func() error {
			_, err := pay.CreateConsultantVoucher(ctx, a, payroll.ConsultantVoucherInput{EmployeeID: theirEmp.ID, GrossAmount: one})
			return err
		},
		"allocation employee": func() error {
			_, err := emps.CreateAllocation(ctx, a, employees.AllocationInput{EmployeeID: theirEmp.ID, ProjectID: uuid.New(), AllocationPercent: one})
			return err
		},
		"task assignee": func() error {
			_, err := tk.Create(ctx, a, tasks.CreateInput{Title: "t", AssigneeID: &theirEmp.ID})
			return err
		},
	}
	for name, call := range refused {
		if err := call(); !errors.Is(err, tenantref.ErrNotFound) {
			t.Errorf("%s of another tenant = %v, want not found", name, err)
		}
	}

	// The tenant's own ids still work.
	if _, err := rec.CreateApplication(ctx, a, ownJob.ID, ownCand.ID, ""); err != nil {
		t.Errorf("own application: %v", err)
	}
	if _, err := app.CreateAppraisal(ctx, a, appraisals.AppraisalInput{CycleID: ownCycle.ID, EmployeeID: ownEmp.ID}); err != nil {
		t.Errorf("own appraisal: %v", err)
	}
	if _, err := perf.SetTarget(ctx, a, ownEmp.ID, ownMetric.ID, one, day, day, nil); err != nil {
		t.Errorf("own target: %v", err)
	}

	// An application that already points at another tenant's candidate cannot be hired from.
	bad := client.Application.Create().SetTenantID(a).SetJobID(ownJob.ID).SetCandidateID(theirCand.ID).SetStatus("offered").SaveX(ctx)
	if _, err := rec.Transition(ctx, a, bad.ID, "hired", true, recruitment.TransitionMeta{}); err == nil {
		t.Error("hiring another tenant's candidate must be refused")
	}
	if n := client.Employee.Query().CountX(ctx); n != 2 {
		t.Errorf("employees = %d, want 2 (nobody hired)", n)
	}

	// Names of another tenant's records are never shown.
	client.HRDetails.Create().SetTenantID(a).SetEmployeeID(ownEmp.ID).SetDepartmentID(theirDept.ID).SetJobTitleID(theirTitle.ID).SaveX(ctx)
	client.AuthTenant.Create().SetID(b).SetSlug("their-org").SetName("Their Org").SaveX(ctx)
	outlet := client.AuthOutlet.Create().SetID(uuid.New()).SetTenantID(b).SetName("Their Branch").SetCode("B").SaveX(ctx)
	ownEmp = client.Employee.UpdateOneID(ownEmp.ID).SetOutletID(outlet.ID).SaveX(ctx)
	views, err := emps.Enrich(ctx, a, []*ent.Employee{ownEmp})
	if err != nil {
		t.Fatal(err)
	}
	if v := views[0]; v.DepartmentName != "" || v.JobTitleName != "" || v.Outlet != "" {
		t.Errorf("another tenant's names leaked: %q %q %q", v.DepartmentName, v.JobTitleName, v.Outlet)
	}
}
