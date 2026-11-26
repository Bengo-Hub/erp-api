package defaults

import (
	"context"
	"database/sql"
	"os"
	"strings"
	"testing"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalquestion"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisaltemplate"
	"github.com/Bengo-Hub/erp-api/internal/ent/goal"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobgroup"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
)

func testClient(t *testing.T) *ent.Client {
	t.Helper()
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_def_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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
	c := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, db)))
	t.Cleanup(func() { _ = c.Close() })
	if err := c.Schema.Create(context.Background()); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return c
}

// TestRemovedDefaultsStayRemoved: a tenant that renamed or deleted a default does not get it back
// on the next run, and a new tenant gets the full set once.
func TestRemovedDefaultsStayRemoved(t *testing.T) {
	c := testClient(t)
	ctx := context.Background()
	s := &Service{orm: c}
	tenant := uuid.New()
	ensure := func() {
		t.Helper()
		for _, f := range []func(context.Context, uuid.UUID) error{s.EnsureLeaveCategories, s.EnsureJobGroups, s.EnsureGoalLibrary, s.EnsureAppraisalTemplate} {
			if err := f(ctx, tenant); err != nil {
				t.Fatal(err)
			}
		}
	}
	ensure()
	if n := c.LeaveCategory.Query().Where(leavecategory.TenantID(tenant)).CountX(ctx); n != len(defaultLeaveCategories) {
		t.Fatalf("leave types: %d", n)
	}
	c.LeaveCategory.Update().Where(leavecategory.TenantID(tenant), leavecategory.Name("Annual Leave")).SetName("Annual").ExecX(ctx)
	c.LeaveCategory.Delete().Where(leavecategory.TenantID(tenant), leavecategory.Name("Study Leave")).ExecX(ctx)
	c.JobGroup.Delete().Where(jobgroup.TenantID(tenant), jobgroup.Title("Grade G")).ExecX(ctx)
	c.Goal.Delete().Where(goal.TenantID(tenant), goal.Title("Drive Innovation")).ExecX(ctx)
	c.AppraisalTemplate.Update().Where(appraisaltemplate.TenantID(tenant)).SetName("Our review").ExecX(ctx)
	ensure()
	for what, n := range map[string]int{
		"Annual Leave": c.LeaveCategory.Query().Where(leavecategory.TenantID(tenant), leavecategory.Name("Annual Leave")).CountX(ctx),
		"Study Leave":  c.LeaveCategory.Query().Where(leavecategory.TenantID(tenant), leavecategory.Name("Study Leave")).CountX(ctx),
		"Grade G":      c.JobGroup.Query().Where(jobgroup.TenantID(tenant), jobgroup.Title("Grade G")).CountX(ctx),
		"goal":         c.Goal.Query().Where(goal.TenantID(tenant), goal.Title("Drive Innovation")).CountX(ctx),
		"template":     c.AppraisalTemplate.Query().Where(appraisaltemplate.TenantID(tenant)).CountX(ctx) - 1,
	} {
		if n != 0 {
			t.Errorf("%s came back on the second run", what)
		}
	}
}

// TestPlatformRevisionFillsOldRows: rows the platform seeded before the defaults carried question
// scoring and the unpaid flag are brought up to the defaults once; a later change by the platform
// owner is kept.
func TestPlatformRevisionFillsOldRows(t *testing.T) {
	c := testClient(t)
	ctx := context.Background()
	s := NewService(c)
	platform := uuid.New()
	// The old seed: the template with questions without category, weight or max score, and the
	// leave types without the paid flag.
	tpl := c.AppraisalTemplate.Create().SetTenantID(platform).SetName(defaultTemplateName).SaveX(ctx)
	for _, q := range defaultAppraisalQuestions {
		c.AppraisalQuestion.Create().SetTenantID(platform).SetTemplateID(tpl.ID).SetQuestionText(q.text).
			SetQuestionType(q.questionType).SetOrder(q.order).SaveX(ctx)
	}
	for _, lc := range defaultLeaveCategories {
		c.LeaveCategory.Create().SetTenantID(platform).SetName(lc.name).SetDefaultAnnualDays(decimal.RequireFromString(lc.annualDays)).
			SetMaxCarryoverDays(decimal.RequireFromString(lc.maxCarryover)).SaveX(ctx)
	}
	if err := s.EnsurePlatform(ctx, platform); err != nil {
		t.Fatal(err)
	}
	for _, q := range defaultAppraisalQuestions {
		got := c.AppraisalQuestion.Query().Where(appraisalquestion.TemplateID(tpl.ID), appraisalquestion.QuestionText(q.text)).OnlyX(ctx)
		if got.Category != q.category || got.Weight != q.weight || got.MaxScore != q.maxScore {
			t.Errorf("%s: category %q weight %v max %d", q.text, got.Category, got.Weight, got.MaxScore)
		}
	}
	unpaid := c.LeaveCategory.Query().Where(leavecategory.TenantID(platform), leavecategory.Name("Unpaid Leave")).OnlyX(ctx)
	if unpaid.IsPaid {
		t.Fatal("Unpaid Leave must be unpaid")
	}
	if n := c.AppraisalQuestion.Query().CountX(ctx); n != len(defaultAppraisalQuestions) {
		t.Fatalf("questions added: %d", n)
	}
	// The platform owner changes a value afterwards; the next deploy keeps it.
	c.LeaveCategory.UpdateOne(unpaid).SetIsPaid(true).ExecX(ctx)
	c.AppraisalQuestion.Update().Where(appraisalquestion.QuestionText("Teamwork")).ClearWeight().ExecX(ctx)
	if err := s.EnsurePlatform(ctx, platform); err != nil {
		t.Fatal(err)
	}
	if !c.LeaveCategory.GetX(ctx, unpaid.ID).IsPaid {
		t.Fatal("a later change by the platform owner was undone")
	}
	if w := c.AppraisalQuestion.Query().Where(appraisalquestion.QuestionText("Teamwork")).OnlyX(ctx).Weight; w != 0 {
		t.Fatalf("a later change by the platform owner was undone: weight %v", w)
	}
}

// TestCompaniesGetNoCopies: a company's defaults are its document sequences only; the shared
// settings are seeded once on the platform tenant, and a second run adds nothing.
func TestCompaniesGetNoCopies(t *testing.T) {
	c := testClient(t)
	ctx := context.Background()
	s := NewService(c)
	company, platform := uuid.New(), uuid.New()
	if err := s.EnsureAll(ctx, company); err != nil {
		t.Fatal(err)
	}
	if n := c.LeaveCategory.Query().CountX(ctx) + c.JobGroup.Query().CountX(ctx) + c.Goal.Query().CountX(ctx) + c.AppraisalTemplate.Query().CountX(ctx); n != 0 {
		t.Fatalf("a company got %d copied settings", n)
	}
	for i := 0; i < 2; i++ {
		if err := s.EnsurePlatform(ctx, platform); err != nil {
			t.Fatal(err)
		}
	}
	if n := c.LeaveCategory.Query().Where(leavecategory.TenantID(platform)).CountX(ctx); n != len(defaultLeaveCategories) {
		t.Fatalf("platform leave types: %d", n)
	}
	if n := c.AppraisalTemplate.Query().Where(appraisaltemplate.TenantID(platform)).CountX(ctx); n != 1 {
		t.Fatalf("platform templates: %d", n)
	}
	if c.JobGroup.Query().Where(jobgroup.TenantID(platform)).CountX(ctx) == 0 || c.Goal.Query().Where(goal.TenantID(platform)).CountX(ctx) == 0 {
		t.Fatal("platform job groups or goals missing")
	}
}
