package employees

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

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
)

// Blank national IDs (and device PINs) are not values: a tenant may have any number of employees
// without one, while a repeated non-blank ID is still refused under the index name the handler
// maps to "Another employee already has this national ID".
func TestBlankNationalIDsAllowed(t *testing.T) {
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_nid_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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
		t.Fatalf("schema: %v", err)
	}

	tenant := uuid.New()
	a := client.Employee.Create().SetTenantID(tenant).SetFirstName("A").SetNationalID("").SetDevicePin("").SaveX(ctx)
	if _, err := client.Employee.Create().SetTenantID(tenant).SetFirstName("B").SetNationalID("").SetDevicePin("").Save(ctx); err != nil {
		t.Fatalf("second employee with a blank national ID and PIN must save: %v", err)
	}
	client.Employee.Create().SetTenantID(tenant).SetFirstName("C").SaveX(ctx)

	// Blanking a second ID works too.
	d := client.Employee.Create().SetTenantID(tenant).SetFirstName("D").SetNationalID("12345678").SaveX(ctx)
	if err := client.Employee.UpdateOneID(d.ID).SetNationalID("").Exec(ctx); err != nil {
		t.Fatalf("blanking a national ID must save: %v", err)
	}

	client.Employee.UpdateOneID(a.ID).SetNationalID("22223333").ExecX(ctx)
	_, err = client.Employee.Create().SetTenantID(tenant).SetFirstName("E").SetNationalID("22223333").Save(ctx)
	if !ent.IsConstraintError(err) || !strings.Contains(err.Error(), "employee_tenant_id_national_id") {
		t.Fatalf("a duplicate non-blank national ID must be refused by employee_tenant_id_national_id, got %v", err)
	}
	// The same ID in another tenant is fine.
	if _, err := client.Employee.Create().SetTenantID(uuid.New()).SetFirstName("F").SetNationalID("22223333").Save(ctx); err != nil {
		t.Fatalf("national ID is unique per tenant only: %v", err)
	}
	blank := client.Employee.Query().Where(employee.TenantID(tenant),
		employee.Or(employee.NationalID(""), employee.NationalIDIsNil())).CountX(ctx)
	if blank < 3 {
		t.Errorf("want at least 3 employees without a national ID, got %d", blank)
	}
}
