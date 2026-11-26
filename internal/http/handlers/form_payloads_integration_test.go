package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
	"github.com/Bengo-Hub/erp-api/internal/modules/appraisals"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
	"github.com/Bengo-Hub/erp-api/internal/modules/recruitment"
	"github.com/Bengo-Hub/erp-api/internal/modules/training"
)

func decodeBody[T any](t *testing.T, raw string) T {
	t.Helper()
	var b T
	if err := json.Unmarshal([]byte(raw), &b); err != nil {
		t.Fatalf("decode %s: %v", raw, err)
	}
	return b
}

// The salary form round trips, and saving part of it keeps the rest. The employee form's basic
// salary, job group and middle name are stored.
func TestIntegration_SalaryAndEmployeeForm(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	tenant, other := uuid.New(), uuid.New()
	svc := employees.NewService(client)
	emp, err := svc.Create(ctx, tenant, employees.CreateInput{FirstName: "Amina", LastName: "Otieno", MiddleName: " Wanjiru "})
	if err != nil {
		t.Fatal(err)
	}

	save := func(raw string) {
		t.Helper()
		in, err := decodeBody[upsertSalaryBody](t, raw).toInput()
		if err != nil {
			t.Fatal(err)
		}
		if _, err := svc.UpsertSalary(ctx, tenant, emp.ID, in); err != nil {
			t.Fatal(err)
		}
	}
	save(`{"monthly_salary":"60000","pay_mode":"weekly","income_tax":"primary","insurance_premium":"2000","pension_contribution":"5000",
		"disability_exempt":true,"preferred_payout_method":"mpesa_b2c","payout_phone":"+254700000000"}`)
	save(`{"monthly_salary":"65000"}`) // only the salary: everything else stays
	v, err := svc.Salary(ctx, tenant, emp.ID)
	if err != nil || v == nil {
		t.Fatalf("salary = %v %v", v, err)
	}
	if v.BasicSalary != "65000.00" || v.PayFrequency != "weekly" || v.PensionContribution != "5000.00" || !v.DisabilityExempt ||
		v.PreferredPayoutMethod != "mpesa_b2c" || v.PayoutPhone != "+254700000000" {
		t.Errorf("salary after a partial save = %+v", v)
	}
	save(`{"monthly_salary":"65000","insurance_premium":"","disability_exempt":false,"preferred_payout_method":"cash"}`)
	v, _ = svc.Salary(ctx, tenant, emp.ID)
	if v.InsurancePremium != "0.00" || v.DisabilityExempt || v.PreferredPayoutMethod != "cash" {
		t.Errorf("explicit values not saved: %+v", v)
	}
	if v, _ := svc.Salary(ctx, other, emp.ID); v != nil {
		t.Error("another tenant must not read the salary")
	}

	// Every form field saves and reloads equal, on the row payroll reads (the newest active one).
	twin := client.Employee.Create().SetTenantID(tenant).SetFirstName("T").SaveX(ctx)
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(twin.ID).SetMonthlySalary(decimal.NewFromInt(1)).
		SetCreatedAt(time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)).SaveX(ctx)
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(twin.ID).SetMonthlySalary(decimal.NewFromInt(3)).
		SetCreatedAt(time.Date(2026, 6, 1, 0, 0, 0, 0, time.UTC)).SetIsActive(false).SaveX(ctx)
	newest := client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(twin.ID).SetMonthlySalary(decimal.NewFromInt(2)).
		SetCreatedAt(time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)).SaveX(ctx)
	in, err := decodeBody[upsertSalaryBody](t, `{"monthly_salary":"80000.50","pay_mode":"daily","income_tax":"secondary","currency":"USD",
		"insurance_premium":"1.10","pension_contribution":"2.20","mortgage_interest":"3.30","disability_exempt":true,
		"preferred_payout_method":"airtel","payout_phone":"+254711111111"}`).toInput()
	if err != nil {
		t.Fatal(err)
	}
	if row, err := svc.UpsertSalary(ctx, tenant, twin.ID, in); err != nil || row.ID != newest.ID {
		t.Fatalf("wrote row %v (%v), want payroll's row %s", row, err, newest.ID)
	}
	got, _ := svc.Salary(ctx, tenant, twin.ID)
	want := employees.SalaryView{BasicSalary: "80000.50", PayFrequency: "daily", IncomeTax: "secondary", Currency: "USD",
		InsurancePremium: "1.10", PensionContribution: "2.20", MortgageInterest: "3.30", DisabilityExempt: true,
		PreferredPayoutMethod: "airtel", PayoutPhone: "+254711111111", Scheduled: []employees.ScheduledSalary{}}
	if got == nil || !reflect.DeepEqual(*got, want) {
		t.Errorf("reload = %+v, want %+v", got, want)
	}

	// Employee form.
	group := client.JobGroup.Create().SetTenantID(tenant).SetTitle("J1").SaveX(ctx)
	foreign := client.JobGroup.Create().SetTenantID(other).SetTitle("X").SaveX(ctx)
	pay, err := decodeBody[updateEmployeeBody](t, `{"basic_salary":"70000","job_group":"`+group.ID.String()+`"}`).salaryInput()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := svc.UpsertSalary(ctx, tenant, emp.ID, pay); err != nil {
		t.Fatal(err)
	}
	views, err := svc.Enrich(ctx, tenant, []*ent.Employee{client.Employee.GetX(ctx, emp.ID)})
	if err != nil {
		t.Fatal(err)
	}
	if views[0].MiddleName != "Wanjiru" || *views[0].BasicSalary != "70000.00" || views[0].JobGroup == nil || views[0].JobGroup.Name != "J1" {
		t.Errorf("employee view = middle %q salary %v group %v", views[0].MiddleName, views[0].BasicSalary, views[0].JobGroup)
	}
	if err := svc.CheckSalary(ctx, tenant, employees.SalaryInput{JobGroupID: &foreign.ID}); err == nil {
		t.Error("another tenant's job group must be refused")
	}
	// A salary save keeps the job group; "" clears it and keeps the salary.
	save(`{"monthly_salary":"71000"}`)
	groupOf := func(id uuid.UUID) (string, *string) {
		t.Helper()
		v, err := svc.Enrich(ctx, tenant, []*ent.Employee{client.Employee.GetX(ctx, id)})
		if err != nil {
			t.Fatal(err)
		}
		if v[0].JobGroup == nil {
			return "", v[0].BasicSalary
		}
		return v[0].JobGroup.Name, v[0].BasicSalary
	}
	if g, s := groupOf(emp.ID); g != "J1" || s == nil || *s != "71000.00" {
		t.Errorf("after a salary save: group %q salary %v", g, s)
	}
	pay, _ = decodeBody[updateEmployeeBody](t, `{"job_group":""}`).salaryInput()
	if _, err := svc.UpsertSalary(ctx, tenant, emp.ID, pay); err != nil {
		t.Fatal(err)
	}
	if g, s := groupOf(emp.ID); g != "" || s == nil || *s != "71000.00" {
		t.Errorf("after clearing: group %q salary %v", g, s)
	}
	// Job group before any salary: shown, but payroll still sees no active salary; setting the
	// salary keeps the group.
	fresh, err := svc.Create(ctx, tenant, employees.CreateInput{FirstName: "B", LastName: "C"})
	if err != nil {
		t.Fatal(err)
	}
	pay, _ = decodeBody[createEmployeeBody](t, `{"job_group":"`+group.ID.String()+`"}`).salaryInput()
	if _, err := svc.UpsertSalary(ctx, tenant, fresh.ID, pay); err != nil {
		t.Fatal(err)
	}
	if g, s := groupOf(fresh.ID); g != "J1" || s != nil {
		t.Errorf("group without salary: %q salary %v, want J1 and none", g, s)
	}
	if n := client.SalaryDetails.Query().Where(salarydetails.EmployeeID(fresh.ID), salarydetails.IsActive(true)).CountX(ctx); n != 0 {
		t.Errorf("active salary rows = %d, want 0", n)
	}
	amount := decimal.NewFromInt(30000)
	if _, err := svc.UpsertSalary(ctx, tenant, fresh.ID, employees.SalaryInput{Monthly: &amount}); err != nil {
		t.Fatal(err)
	}
	if g, s := groupOf(fresh.ID); g != "J1" || s == nil || *s != "30000.00" {
		t.Errorf("after the first salary: group %q salary %v", g, s)
	}
	if n := client.SalaryDetails.Query().Where(salarydetails.EmployeeID(fresh.ID)).CountX(ctx); n != 1 {
		t.Errorf("salary rows = %d, want 1", n)
	}
	if in, _ := decodeBody[updateEmployeeBody](t, `{"first_name":"A"}`).salaryInput(); !in.Empty() {
		t.Error("no pay fields must mean no change")
	}
}

// Appraisal templates and questions: edit and delete, tenant-scoped, refused once in use.
func TestIntegration_TemplateAndQuestionEdit(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	tenant, other := uuid.New(), uuid.New()
	svc := appraisals.NewService(client)
	tpl, err := svc.CreateTemplate(ctx, tenant, "Annual", "", nil)
	if err != nil {
		t.Fatal(err)
	}
	weight := 2.0
	q, err := svc.AddQuestion(ctx, tenant, appraisals.QuestionInput{TemplateID: tpl.ID, QuestionText: "Quality", Weight: &weight, Category: "Work"})
	if err != nil {
		t.Fatal(err)
	}
	off := false
	if row, err := svc.UpdateTemplate(ctx, tenant, tpl.ID, "Yearly", "d", &off); err != nil || row.Name != "Yearly" || row.IsActive {
		t.Fatalf("update template = %+v %v", row, err)
	}
	if _, err := svc.UpdateTemplate(ctx, other, tpl.ID, "X", "", nil); !ent.IsNotFound(err) {
		t.Errorf("cross-tenant template update = %v, want not found", err)
	}
	if row, err := svc.UpdateQuestion(ctx, tenant, q.ID, appraisals.QuestionInput{QuestionText: "Output", IsRequired: true}); err != nil ||
		row.QuestionText != "Output" || row.TemplateID != tpl.ID || row.Category != "" {
		t.Fatalf("update question = %+v %v", row, err)
	}
	if err := svc.DeleteQuestion(ctx, other, q.ID); !ent.IsNotFound(err) {
		t.Errorf("cross-tenant question delete = %v, want not found", err)
	}
	if err := svc.DeleteTemplate(ctx, other, tpl.ID); !ent.IsNotFound(err) {
		t.Errorf("cross-tenant template delete = %v, want not found", err)
	}

	app := client.Appraisal.Create().SetTenantID(tenant).SetCycleID(uuid.New()).SetEmployeeID(uuid.New()).SetTemplateID(tpl.ID).SaveX(ctx)
	client.AppraisalResponse.Create().SetTenantID(tenant).SetAppraisalID(app.ID).SetQuestionID(q.ID).SetResponse("Good").SaveX(ctx)
	if _, err := svc.UpdateQuestion(ctx, tenant, q.ID, appraisals.QuestionInput{QuestionText: "X"}); !errors.Is(err, appraisals.ErrQuestionAnswered) {
		t.Errorf("edit of an answered question = %v", err)
	}
	if err := svc.DeleteQuestion(ctx, tenant, q.ID); !errors.Is(err, appraisals.ErrQuestionAnswered) {
		t.Errorf("delete of an answered question = %v", err)
	}
	if err := svc.DeleteTemplate(ctx, tenant, tpl.ID); !errors.Is(err, appraisals.ErrTemplateInUse) {
		t.Errorf("delete of a used template = %v", err)
	}

	spare, _ := svc.CreateTemplate(ctx, tenant, "Spare", "", nil)
	if _, err := svc.AddQuestion(ctx, tenant, appraisals.QuestionInput{TemplateID: spare.ID, QuestionText: "A"}); err != nil {
		t.Fatal(err)
	}
	if err := svc.DeleteTemplate(ctx, tenant, spare.ID); err != nil {
		t.Fatal(err)
	}
	if qs, _ := svc.ListQuestions(ctx, tenant, spare.ID); len(qs) != 0 {
		t.Errorf("questions left behind: %v", qs)
	}
}

// Job postings: the edit form's status and deadline are saved; deletion is tenant-scoped and
// refused once someone applied. A course edit without capacity keeps it. A claim's description
// and an advance's inactive state survive edits.
func TestIntegration_PostingCourseClaimAdvanceForms(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	tenant, other := uuid.New(), uuid.New()
	rec := recruitment.NewService(client)

	p, err := rec.CreatePosting(ctx, tenant, decodeBody[postingBody](t, `{"title":"Driver","status":"draft"}`).toInput())
	if err != nil {
		t.Fatal(err)
	}
	p, err = rec.UpdatePosting(ctx, tenant, p.ID, decodeBody[postingBody](t,
		`{"title":"Driver","status":"open","num_positions":2,"application_deadline":"2026-12-31T00:00:00Z"}`).toInput())
	if err != nil || string(p.Status) != "open" || p.ApplicationDeadline == nil || p.NumPositions != 2 {
		t.Fatalf("posting after edit = %+v %v", p, err)
	}
	if err := rec.DeletePosting(ctx, other, p.ID); !ent.IsNotFound(err) {
		t.Errorf("cross-tenant posting delete = %v, want not found", err)
	}
	app := client.Application.Create().SetTenantID(tenant).SetJobID(p.ID).SetCandidateID(uuid.New()).SaveX(ctx)
	if err := rec.DeletePosting(ctx, tenant, p.ID); !errors.Is(err, recruitment.ErrPostingInUse) {
		t.Errorf("delete of a posting with applications = %v", err)
	}
	client.Application.DeleteOneID(app.ID).ExecX(ctx)
	if err := rec.DeletePosting(ctx, tenant, p.ID); err != nil {
		t.Errorf("delete posting = %v", err)
	}

	tr := training.NewService(client)
	day, capacity := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC), 12
	course, err := tr.CreateCourse(ctx, tenant, training.CourseInput{Title: "First aid", StartDate: day, EndDate: day, Capacity: &capacity})
	if err != nil {
		t.Fatal(err)
	}
	if course, err = tr.UpdateCourse(ctx, tenant, course.ID, training.CourseInput{Title: "First aid 2", StartDate: day, EndDate: day}); err != nil || course.Capacity != 12 {
		t.Errorf("course after an edit without capacity = %+v %v", course, err)
	}

	pay := payroll.NewService(client, nil)
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("A").SaveX(ctx)
	in, err := decodeBody[claimBody](t, `{"employee_id":"`+emp.ID.String()+`","claim_type":"reimbursement","amount":"100","description":"Taxi to site"}`).toInput()
	if err != nil {
		t.Fatal(err)
	}
	claim, err := pay.CreateClaim(ctx, tenant, in)
	if err != nil {
		t.Fatal(err)
	}
	in, _ = decodeBody[claimBody](t, `{"amount":"150"}`).toInput()
	if claim, err = pay.UpdateClaim(ctx, tenant, claim.ID, in); err != nil || claim.Metadata["description"] != "Taxi to site" {
		t.Errorf("claim description after an edit = %v %v", claim.Metadata, err)
	}

	rin, _ := decodeBody[recoverableBody](t, `{"employee_id":"`+emp.ID.String()+`","amount":"1000","no_of_installments":2}`).toInput()
	adv, err := pay.CreateAdvance(ctx, tenant, rin)
	if err != nil || !adv.IsActive {
		t.Fatalf("advance = %+v %v", adv, err)
	}
	client.Advance.UpdateOneID(adv.ID).SetIsActive(false).ExecX(ctx) // disapproved
	rin, _ = decodeBody[recoverableBody](t, `{"amount":"1200","no_of_installments":2}`).toInput()
	if adv, err = pay.UpdateAdvance(ctx, tenant, adv.ID, rin); err != nil || adv.IsActive || !adv.AmountIssued.Equal(decimal.NewFromInt(1200)) {
		t.Errorf("editing a disapproved advance = %+v %v, want it still inactive", adv, err)
	}
}
