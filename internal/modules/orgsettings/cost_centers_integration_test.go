package orgsettings

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"strings"
	"testing"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

type fakeCenters struct {
	list []treasury.CostCenter
	err  error
}

func (f *fakeCenters) ListCostCenters(context.Context, uuid.UUID) ([]treasury.CostCenter, error) {
	return f.list, f.err
}

func orgTestClient(t *testing.T) *ent.Client {
	t.Helper()
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_org_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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

// A department takes only an active treasury cost centre of the tenant; when treasury is down the
// save goes ahead. The nightly check stores missing and inactive ids, and a treasury failure.
func TestIntegration_DepartmentCostCenters(t *testing.T) {
	client := orgTestClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	active, retired, unknown := uuid.New(), uuid.New(), uuid.New()
	src := &fakeCenters{list: []treasury.CostCenter{{ID: active, Name: "Ops", IsActive: true}, {ID: retired, Name: "Old", IsActive: false}}}
	svc := NewService(client).WithCostCenters(src, zap.NewNop())

	if _, err := svc.CreateDepartment(ctx, tenant, NamedInput{Title: "Ops", CostCenterSet: true, CostCenterID: &active}); err != nil {
		t.Fatalf("active cost centre refused: %v", err)
	}
	for _, id := range []uuid.UUID{retired, unknown} {
		id := id
		if _, err := svc.CreateDepartment(ctx, tenant, NamedInput{Title: "X", CostCenterSet: true, CostCenterID: &id}); !errors.Is(err, ErrUnknownCostCenter) {
			t.Errorf("cost centre %s: err %v, want ErrUnknownCostCenter", id, err)
		}
	}
	src.err = errors.New("treasury down")
	if _, err := svc.CreateDepartment(ctx, tenant, NamedInput{Title: "Later", CostCenterSet: true, CostCenterID: &unknown}); err != nil {
		t.Fatalf("treasury down must not block the save: %v", err)
	}
	src.err = nil
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("A").SaveX(ctx)
	client.EmployeeProjectAllocation.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetProjectID(uuid.New()).
		SetProjectName("P").SetAllocationPercent(decimal.NewFromInt(50)).SetCostCenterID(retired).SaveX(ctx)

	cron := NewCostCenterCron(svc, zap.NewNop(), 0)
	cron.RunOnce(ctx)
	res, err := svc.LastCostCenterCheck(ctx, tenant)
	if err != nil {
		t.Fatal(err)
	}
	reasons := map[string]string{}
	for _, p := range res.Problems {
		reasons[p.Record+":"+p.Name] = p.Reason
	}
	if len(res.Problems) != 2 || reasons["department:Later"] != "missing" || reasons["project_allocation:P"] != "inactive" {
		t.Errorf("problems %v, want Later missing and P inactive", res.Problems)
	}

	src.err = errors.New("treasury down")
	cron.RunOnce(ctx)
	if res, _ = svc.LastCostCenterCheck(ctx, tenant); res.Error == "" {
		t.Error("a failed check must be stored with its error")
	}
}
