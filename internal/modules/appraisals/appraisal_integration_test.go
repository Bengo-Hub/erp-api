package appraisals

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisal"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalquestion"
)

// openTestClient opens an ent client on a throwaway Postgres schema. Needs
// ERP_TEST_DATABASE_URL; the test is skipped without it.
func openTestClient(t *testing.T) *ent.Client {
	t.Helper()
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_apr_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	if _, err := admin.Exec("CREATE SCHEMA " + schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = admin.Exec("DROP SCHEMA " + schema + " CASCADE"); _ = admin.Close() })
	sep := "?"
	if strings.Contains(url, "?") {
		sep = "&"
	}
	db, err := sql.Open("pgx", url+sep+"search_path="+schema)
	if err != nil {
		t.Fatal(err)
	}
	client := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, db)))
	t.Cleanup(func() { _ = client.Close() })
	if err := client.Schema.Create(context.Background()); err != nil {
		t.Fatal(err)
	}
	return client
}

// TestAppraisalEvaluationOnPostgres: names on get and list, questions inherited from the
// system template, a second answer replaces the first, the first answer starts a draft,
// and a submitted appraisal refuses answers.
func TestAppraisalEvaluationOnPostgres(t *testing.T) {
	client := openTestClient(t)
	ctx := context.Background()
	tenant, system := uuid.New(), uuid.New()
	svc := NewService(client).WithSystemTenant(system)

	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("Jane").SetLastName("Wanjiru").
		SetEmployeeNumber("1001").SaveX(ctx)
	boss := client.Employee.Create().SetTenantID(tenant).SetFirstName("Peter").SetLastName("Otieno").SaveX(ctx)
	cycle, err := svc.CreateCycle(ctx, tenant, CycleInput{Name: "2026 H2", StartDate: time.Now(), EndDate: time.Now().AddDate(0, 6, 0)})
	if err != nil {
		t.Fatal(err)
	}
	tpl := client.AppraisalTemplate.Create().SetTenantID(system).SetName("Standard").SetIsActive(true).SaveX(ctx)
	q := client.AppraisalQuestion.Create().SetTenantID(system).SetTemplateID(tpl.ID).
		SetQuestionText("Quality of work").SetQuestionType(appraisalquestion.QuestionTypeRating).SaveX(ctx)

	a, err := svc.CreateAppraisal(ctx, tenant, AppraisalInput{CycleID: cycle.ID, EmployeeID: emp.ID, EvaluatorID: &boss.ID, TemplateID: &tpl.ID})
	if err != nil {
		t.Fatal(err)
	}

	v, err := svc.GetAppraisal(ctx, tenant, a.ID)
	if err != nil {
		t.Fatal(err)
	}
	if v.EmployeeName != "Jane Wanjiru" || v.EmployeeNumber != "1001" || v.EvaluatorName != "Peter Otieno" ||
		v.CycleName != "2026 H2" || v.TemplateName != "Standard" {
		t.Fatalf("names not filled: %+v", v)
	}
	if _, err := svc.GetAppraisal(ctx, uuid.New(), a.ID); !ent.IsNotFound(err) {
		t.Fatalf("another tenant must not load the appraisal, got %v", err)
	}

	qs, err := svc.ListQuestions(ctx, tenant, tpl.ID)
	if err != nil || len(qs) != 1 {
		t.Fatalf("inherited questions: %v %d", err, len(qs))
	}

	if _, err := svc.AddResponse(ctx, tenant, ResponseInput{AppraisalID: a.ID, QuestionID: q.ID, Response: "Good", Rating: "3"}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.AddResponse(ctx, tenant, ResponseInput{AppraisalID: a.ID, QuestionID: q.ID, Response: "Very good", Rating: "4.5"}); err != nil {
		t.Fatal(err)
	}
	rs, err := svc.ListResponses(ctx, tenant, a.ID)
	if err != nil || len(rs) != 1 || rs[0].Response != "Very good" || rs[0].Rating == nil || rs[0].Rating.String() != "4.5" {
		t.Fatalf("second answer must replace the first: %v %+v", err, rs)
	}
	if cur := client.Appraisal.GetX(ctx, a.ID); cur.Status != appraisal.StatusInProgress {
		t.Fatalf("first answer must start the appraisal, status %s", cur.Status)
	}
	if _, err := svc.AddResponse(ctx, tenant, ResponseInput{AppraisalID: a.ID, QuestionID: q.ID, Rating: "6"}); err == nil {
		t.Fatal("rating above 5 must be refused")
	}

	if _, err := svc.SetAppraisalStatus(ctx, tenant, a.ID, "completed", "4.5", ""); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.AddResponse(ctx, tenant, ResponseInput{AppraisalID: a.ID, QuestionID: q.ID, Rating: "2"}); !errors.Is(err, ErrAppraisalLocked) {
		t.Fatalf("submitted appraisal must refuse answers, got %v", err)
	}
	if _, err := svc.SetAppraisalStatus(ctx, tenant, a.ID, "submitted", "", ""); err == nil {
		t.Fatal("unknown status must be refused")
	}

	views, err := svc.DescribeAppraisals(ctx, tenant, []*ent.Appraisal{client.Appraisal.GetX(ctx, a.ID)})
	if err != nil || len(views) != 1 || views[0].EmployeeName != "Jane Wanjiru" {
		t.Fatalf("list names: %v %+v", err, views)
	}
}

// TestGoalCategoryAndWeightOnPostgres: category and weight survive in metadata and come
// back with the employee's name; a negative weight is refused.
func TestGoalCategoryAndWeightOnPostgres(t *testing.T) {
	client := openTestClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	svc := NewService(client)
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("Jane").SetLastName("Wanjiru").SaveX(ctx)

	g, err := svc.CreateGoal(ctx, tenant, GoalInput{EmployeeID: &emp.ID, Title: "Cut stock losses", Category: " Operations ", Weight: "25"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := svc.CreateGoal(ctx, tenant, GoalInput{EmployeeID: &emp.ID, Title: "x", Weight: "-1"}); err == nil {
		t.Fatal("negative weight must be refused")
	}
	rows, err := svc.ListGoals(ctx, tenant, nil)
	if err != nil {
		t.Fatal(err)
	}
	views, err := svc.DescribeGoals(ctx, tenant, rows)
	if err != nil || len(views) != 1 {
		t.Fatalf("goals: %v %d", err, len(views))
	}
	v := views[0]
	if v.ID != g.ID || v.EmployeeName != "Jane Wanjiru" || v.Category != "Operations" || v.Weight != "25" {
		t.Fatalf("goal view: %+v", v)
	}
}
