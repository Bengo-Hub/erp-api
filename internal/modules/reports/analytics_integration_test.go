package reports

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
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// Runs against Postgres when ERP_TEST_DATABASE_URL is set (a throwaway schema per run), e.g.
//
//	ERP_TEST_DATABASE_URL=postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable go test ./internal/modules/reports/
func analyticsClient(t *testing.T) *ent.Client {
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	schema := "erp_it_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := admin.ExecContext(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = admin.ExecContext(context.Background(), "DROP SCHEMA "+schema+" CASCADE")
		_ = admin.Close()
	})
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
	if err := client.Schema.Create(ctx); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return client
}

func TestIntegration_HRMAnalytics(t *testing.T) {
	client := analyticsClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	now := time.Now().UTC()

	ops, err := client.Department.Create().SetTenantID(tenant).SetTitle("Operations").Save(ctx)
	if err != nil {
		t.Fatal(err)
	}
	emp := func(gender string, terminated bool, dept *uuid.UUID, joined time.Time, empType string) uuid.UUID {
		e, err := client.Employee.Create().SetTenantID(tenant).SetFirstName("E").SetGender(gender).SetTerminated(terminated).Save(ctx)
		if err != nil {
			t.Fatal(err)
		}
		c := client.HRDetails.Create().SetTenantID(tenant).SetEmployeeID(e.ID).SetDateJoined(joined).SetNillableDepartmentID(dept)
		if empType != "" {
			c = c.SetEmploymentType(empType)
		}
		if _, err := c.Save(ctx); err != nil {
			t.Fatal(err)
		}
		return e.ID
	}
	a := emp("female", false, &ops.ID, now.AddDate(0, 0, -2), "permanent")
	b := emp("male", false, &ops.ID, now.AddDate(-2, 0, 0), "contract")
	emp("", false, nil, now.AddDate(-1, 0, 0), "")
	emp("male", true, &ops.ID, now.AddDate(0, 0, -1), "permanent") // terminated: excluded
	// Another tenant never counts.
	other, _ := client.Employee.Create().SetTenantID(uuid.New()).SetFirstName("X").Save(ctx)
	_ = other

	for _, days := range []int{10, 45, 200} {
		if _, err := client.Contract.Create().SetTenantID(tenant).SetEmployeeID(b).SetStatus("active").
			SetEndDate(now.AddDate(0, 0, days)).Save(ctx); err != nil {
			t.Fatal(err)
		}
	}
	lastMonth := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC).AddDate(0, -1, 0)
	for _, p := range []struct {
		emp   uuid.UUID
		when  time.Time
		gross string
	}{{a, lastMonth, "100000"}, {b, lastMonth, "50000"}, {a, lastMonth.AddDate(0, -1, 0), "90000"}} {
		if _, err := client.Payslip.Create().SetTenantID(tenant).SetEmployeeID(p.emp).SetPaymentPeriod(p.when).
			SetGrossPay(decimal.RequireFromString(p.gross)).SetNetPay(decimal.RequireFromString(p.gross).Mul(decimal.NewFromFloat(0.8))).Save(ctx); err != nil {
			t.Fatal(err)
		}
	}

	s := NewService(client)
	from := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC).AddDate(0, 0, -7)
	res, err := s.HRMAnalytics(ctx, tenant, from, now)
	if err != nil {
		t.Fatal(err)
	}
	if res.Headcount != 3 || res.Terminated != 1 {
		t.Fatalf("headcount %d terminated %d, want 3/1", res.Headcount, res.Terminated)
	}
	if res.NewHires != 1 {
		t.Fatalf("new hires %d, want 1 (the terminated recent hire excluded)", res.NewHires)
	}
	if len(res.ByDepartment) != 2 || res.ByDepartment[0].Label != "Operations" || res.ByDepartment[0].Count != 2 {
		t.Fatalf("by department: %+v", res.ByDepartment)
	}
	notSet := 0
	for _, g := range res.ByGender {
		if g.Label == "Not set" {
			notSet = g.Count
		}
	}
	if len(res.ByGender) != 3 || notSet != 1 {
		t.Fatalf("by gender: %+v", res.ByGender)
	}
	if res.ContractsExpiry.Within30 != 1 || res.ContractsExpiry.Within60 != 2 || res.ContractsExpiry.Within90 != 2 {
		t.Fatalf("contracts: %+v", res.ContractsExpiry)
	}
	if len(res.PayrollTrend) != 2 || !res.PayrollTrend[1].Gross.Equal(decimal.RequireFromString("150000")) || res.PayrollTrend[1].Employees != 2 {
		t.Fatalf("payroll trend: %+v", res.PayrollTrend)
	}
	if len(res.PayrollByDept) != 1 || res.PayrollByDept[0].Label != "Operations" || !res.PayrollByDept[0].Amount.Equal(decimal.RequireFromString("150000")) {
		t.Fatalf("payroll by department: %+v", res.PayrollByDept)
	}
}

func TestIntegration_HeadcountSummaryGrouped(t *testing.T) {
	client := analyticsClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	for _, term := range []bool{false, false, true} {
		if _, err := client.Employee.Create().SetTenantID(tenant).SetFirstName("E").SetTerminated(term).Save(ctx); err != nil {
			t.Fatal(err)
		}
	}
	rep, err := NewService(client).HeadcountSummary(ctx, tenant, nil)
	if err != nil {
		t.Fatal(err)
	}
	if rep.Totals["total"] != 3 || rep.Totals["active"] != 2 || rep.Totals["terminated"] != 1 {
		t.Fatalf("totals: %+v", rep.Totals)
	}
}
