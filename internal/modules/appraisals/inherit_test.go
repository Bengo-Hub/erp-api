package appraisals

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalquestion"
)

// TestInheritedTemplatesOnPostgres: a company uses the platform template without a copy, changes
// its description and a question's wording for itself, reverts them, cannot rename it or change a
// question its staff answered, and its own template of the same name replaces the platform one.
func TestInheritedTemplatesOnPostgres(t *testing.T) {
	client := openTestClient(t)
	ctx := context.Background()
	tenant, other, system := uuid.New(), uuid.New(), uuid.New()
	svc := NewService(client).WithSystemTenant(system)
	tpl := client.AppraisalTemplate.Create().SetTenantID(system).SetName("Standard").SetDescription("Yearly").SetIsActive(true).SaveX(ctx)
	q := client.AppraisalQuestion.Create().SetTenantID(system).SetTemplateID(tpl.ID).SetOrder(1).
		SetQuestionText("Quality of work").SetQuestionType(appraisalquestion.QuestionTypeRating).SaveX(ctx)

	got, err := svc.UpdateTemplate(ctx, tenant, tpl.ID, "Standard", "Half-yearly", nil)
	if err != nil || got.Description != "Half-yearly" || got.ID != tpl.ID {
		t.Fatalf("customise template: %v %v", got, err)
	}
	if _, err := svc.UpdateTemplate(ctx, tenant, tpl.ID, "Mine", "", nil); !errors.Is(err, ErrInheritedTemplate) {
		t.Fatalf("rename: %v", err)
	}
	if _, err := svc.UpdateQuestion(ctx, tenant, q.ID, QuestionInput{QuestionText: "Quality and accuracy", IsRequired: true, Order: 1}); err != nil {
		t.Fatal(err)
	}
	mine, _ := svc.ListTemplates(ctx, tenant)
	theirs, _ := svc.ListTemplates(ctx, other)
	qs, _ := svc.ListQuestions(ctx, tenant, tpl.ID)
	oqs, _ := svc.ListQuestions(ctx, other, tpl.ID)
	if len(mine) != 1 || mine[0].Description != "Half-yearly" || theirs[0].Description != "Yearly" ||
		qs[0].QuestionText != "Quality and accuracy" || oqs[0].QuestionText != "Quality of work" {
		t.Fatalf("views: %v %v %v %v", mine, theirs, qs, oqs)
	}
	if n := client.AppraisalTemplate.Query().CountX(ctx); n != 1 {
		t.Fatalf("template copied: %d", n)
	}
	// The lists say what is inherited and what the company changed.
	tv, err := svc.ListTemplateViews(ctx, tenant)
	if err != nil || len(tv) != 1 || !tv[0].Inherited || !tv[0].Customised {
		t.Fatalf("template views: %+v %v", tv, err)
	}
	if otv, _ := svc.ListTemplateViews(ctx, other); !otv[0].Inherited || otv[0].Customised {
		t.Fatalf("other company's template view: %+v", otv)
	}
	if qv, err := svc.ListAllQuestions(ctx, tenant); err != nil || len(qv) != 1 || !qv[0].Inherited || !qv[0].Customised {
		t.Fatalf("question views: %+v %v", qv, err)
	}

	// A question the company's staff answered is no longer changed.
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("Jane").SetLastName("W").SaveX(ctx)
	cycle, _ := svc.CreateCycle(ctx, tenant, CycleInput{Name: "2026", StartDate: time.Now(), EndDate: time.Now().AddDate(0, 6, 0)})
	a, err := svc.CreateAppraisal(ctx, tenant, AppraisalInput{CycleID: cycle.ID, EmployeeID: emp.ID, TemplateID: &tpl.ID})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := svc.AddResponse(ctx, tenant, ResponseInput{AppraisalID: a.ID, QuestionID: q.ID, Rating: "4"}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.UpdateQuestion(ctx, tenant, q.ID, QuestionInput{QuestionText: "Other", Order: 1}); !errors.Is(err, ErrQuestionAnswered) {
		t.Fatalf("answered question: %v", err)
	}

	if r, err := svc.RevertTemplate(ctx, tenant, tpl.ID); err != nil || r.Description != "Yearly" {
		t.Fatalf("revert template: %v %v", r, err)
	}
	if _, err := svc.RevertTemplate(ctx, tenant, tpl.ID); !errors.Is(err, ErrNothingToRevert) {
		t.Fatalf("second revert: %v", err)
	}
	if r, err := svc.RevertQuestion(ctx, tenant, q.ID); err != nil || r.QuestionText != "Quality of work" {
		t.Fatalf("revert question: %v %v", r, err)
	}

	// The company's own "standard " template replaces the platform one.
	client.AppraisalTemplate.Create().SetTenantID(tenant).SetName("standard ").SaveX(ctx)
	if mine, _ = svc.ListTemplates(ctx, tenant); len(mine) != 1 || mine[0].TenantID != tenant {
		t.Fatalf("own template: %v", mine)
	}
	if _, err := svc.RevertTemplate(ctx, tenant, tpl.ID); !ent.IsNotFound(err) {
		t.Fatalf("replaced template: %v", err)
	}
}

// TestInheritedSampleGoalsOnPostgres: the goal library holds the platform's sample goals without
// a copy; a company changes one's description and category for itself and reverts it, cannot
// rename or assign it, and its own goal of the same title replaces it.
func TestInheritedSampleGoalsOnPostgres(t *testing.T) {
	client := openTestClient(t)
	ctx := context.Background()
	tenant, other, system := uuid.New(), uuid.New(), uuid.New()
	svc := NewService(client).WithSystemTenant(system)
	g := client.Goal.Create().SetTenantID(system).SetTitle("Reduce customer complaints").SetDescription("By 20%").SetIsTemplate(true).SaveX(ctx)
	yes := true
	library := func(tn uuid.UUID) []*ent.Goal {
		rows, err := svc.ListGoals(ctx, tn, GoalFilter{IsTemplate: &yes})
		if err != nil {
			t.Fatal(err)
		}
		return rows
	}
	if rows := library(tenant); len(rows) != 1 || rows[0].ID != g.ID {
		t.Fatalf("library: %v", rows)
	}
	got, err := svc.UpdateGoal(ctx, tenant, g.ID, GoalInput{Title: "Reduce customer complaints", Description: "By 30%", Category: "Quality"})
	if err != nil || got.Description != "By 30%" || got.Metadata["category"] != "Quality" {
		t.Fatalf("customise: %v %v", got, err)
	}
	if rows := library(other); rows[0].Description != "By 20%" {
		t.Fatalf("other company: %v", rows[0])
	}
	if rows := library(tenant); rows[0].Description != "By 30%" {
		t.Fatalf("company view: %v", rows[0])
	}
	if gv, err := svc.DescribeGoals(ctx, tenant, library(tenant)); err != nil || !gv[0].Inherited || !gv[0].Customised {
		t.Fatalf("goal views: %+v %v", gv, err)
	}
	emp := uuid.New()
	if _, err := svc.UpdateGoal(ctx, tenant, g.ID, GoalInput{Title: "Reduce customer complaints", EmployeeID: &emp}); !errors.Is(err, ErrInheritedGoal) {
		t.Fatalf("assign: %v", err)
	}
	if _, err := svc.UpdateGoal(ctx, tenant, g.ID, GoalInput{Title: "Other"}); !errors.Is(err, ErrInheritedGoal) {
		t.Fatalf("rename: %v", err)
	}
	if r, err := svc.RevertGoal(ctx, tenant, g.ID); err != nil || r.Description != "By 20%" {
		t.Fatalf("revert: %v %v", r, err)
	}
	client.Goal.Create().SetTenantID(tenant).SetTitle("reduce customer complaints").SetIsTemplate(true).SaveX(ctx)
	if rows := library(tenant); len(rows) != 1 || rows[0].TenantID != tenant {
		t.Fatalf("own goal: %v", rows)
	}
	if n := client.Goal.Query().CountX(ctx); n != 2 {
		t.Fatalf("goals copied: %d", n)
	}
}
