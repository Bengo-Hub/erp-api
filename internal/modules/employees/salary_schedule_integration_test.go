package employees

import (
	"context"
	"database/sql"
	"os"
	"strings"
	"testing"
	"time"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
)

// A raise set from a later month leaves today's salary as it is, shows as scheduled, is paid from
// its month on, and keeps the earlier row; a change for a past month is refused.
func TestIntegration_ScheduledSalary(t *testing.T) {
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_sal_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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
	ctx := context.Background()
	if err := client.Schema.Create(ctx); err != nil {
		t.Fatal(err)
	}
	svc := NewService(client)
	tenant := uuid.New()
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("Wanjiru").SaveX(ctx)
	amount := func(s string) *decimal.Decimal { d := decimal.RequireFromString(s); return &d }

	if _, err := svc.UpsertSalary(ctx, tenant, emp.ID, SalaryInput{Monthly: amount("50000")}); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	next := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC).AddDate(0, 2, 0)
	if _, err := svc.UpsertSalary(ctx, tenant, emp.ID, SalaryInput{Monthly: amount("60000"), EffectiveFrom: &next}); err != nil {
		t.Fatal(err)
	}
	v, err := svc.Salary(ctx, tenant, emp.ID)
	if err != nil {
		t.Fatal(err)
	}
	if v.BasicSalary != "50000.00" || len(v.Scheduled) != 1 || v.Scheduled[0].BasicSalary != "60000.00" || v.Scheduled[0].EffectiveFrom != next.Format("2006-01") {
		t.Errorf("salary view = %+v", v)
	}
	rows := client.SalaryDetails.Query().Where(salarydetails.EmployeeID(emp.ID)).AllX(ctx)
	if len(rows) != 2 {
		t.Fatalf("rows = %d, want the old and the scheduled", len(rows))
	}
	if got := SalaryInForce(rows, MonthEnd(next.AddDate(0, -1, 0))); !got.MonthlySalary.Equal(decimal.NewFromInt(50000)) {
		t.Errorf("month before: %s", got.MonthlySalary)
	}
	if got := SalaryInForce(rows, MonthEnd(next)); !got.MonthlySalary.Equal(decimal.NewFromInt(60000)) {
		t.Errorf("scheduled month: %s", got.MonthlySalary)
	}
	// Saving the same month again edits that row, not a third one.
	if _, err := svc.UpsertSalary(ctx, tenant, emp.ID, SalaryInput{Monthly: amount("61000"), EffectiveFrom: &next}); err != nil {
		t.Fatal(err)
	}
	if n := client.SalaryDetails.Query().Where(salarydetails.EmployeeID(emp.ID)).CountX(ctx); n != 2 {
		t.Errorf("rows = %d after editing the scheduled month, want 2", n)
	}
	past := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC).AddDate(0, -1, 0)
	if _, err := svc.UpsertSalary(ctx, tenant, emp.ID, SalaryInput{Monthly: amount("1"), EffectiveFrom: &past}); err == nil {
		t.Error("a change for a month already paid must be refused")
	}

	// A salary in force (or past) is history and cannot be cancelled; a scheduled one can.
	thisMonth := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC)
	if _, err := svc.UpsertSalary(ctx, tenant, emp.ID, SalaryInput{Monthly: amount("55000"), EffectiveFrom: &thisMonth}); err != nil {
		t.Fatal(err)
	}
	if err := svc.CancelScheduledSalary(ctx, tenant, emp.ID, thisMonth); err == nil {
		t.Error("the salary in force this month must not be cancellable")
	}
	if err := svc.CancelScheduledSalary(ctx, uuid.New(), emp.ID, next); err == nil {
		t.Error("another tenant must not cancel this employee's salary")
	}
	if err := svc.CancelScheduledSalary(ctx, tenant, emp.ID, next); err != nil {
		t.Fatalf("cancel scheduled: %v", err)
	}
	if v, _ := svc.Salary(ctx, tenant, emp.ID); len(v.Scheduled) != 0 || v.BasicSalary != "55000.00" {
		t.Errorf("after cancel = %+v", v)
	}
	if err := svc.CancelScheduledSalary(ctx, tenant, emp.ID, next); err == nil {
		t.Error("cancelling a month with nothing scheduled must say so")
	}
}
