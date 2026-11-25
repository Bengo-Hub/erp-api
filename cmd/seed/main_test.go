package main

import (
	"context"
	"database/sql"
	"os"
	"slices"
	"strings"
	"testing"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/role"
)

func seedTestClient(t *testing.T) *ent.Client {
	t.Helper()
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_seed_" + uuid.NewString()[:8]
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

// TestSeedTakesLeaveManageFromStaff: the seed drops hrm.leave.manage from the one global staff
// role, keeps the rest of it, changes no user's assignment and no tenant's own role, and a second
// run changes nothing more.
func TestSeedTakesLeaveManageFromStaff(t *testing.T) {
	c := seedTestClient(t)
	ctx := context.Background()
	manage, err := upsertPermission(ctx, c, "hrm.leave.manage")
	if err != nil {
		t.Fatal(err)
	}
	global := c.Role.Create().SetRoleCode("staff").SetName("Staff").SetIsSystemRole(true).AddPermissions(manage).SaveX(ctx)
	tenant, user := uuid.New(), uuid.New()
	own := c.Role.Create().SetTenantID(tenant).SetRoleCode("staff").SetName("Own staff").AddPermissions(manage).SaveX(ctx)
	u := c.CustomUser.Create().SetID(user).SetTenantID(tenant).SetExternalID(user.String()).SetEmail("s@example.com").SaveX(ctx)
	c.UserRoleAssignment.Create().SetTenantID(tenant).SetUserID(u.ID).SetRoleID(global.ID).SaveX(ctx)

	codes := func(r *ent.Role) []string {
		var out []string
		for _, p := range r.QueryPermissions().AllX(ctx) {
			out = append(out, p.PermissionCode)
		}
		slices.Sort(out)
		return out
	}
	want := []string{"hrm.attendance.view", "hrm.employee.view", "hrm.leave.view", "hrm.payroll.view", "tasks.view"}
	for run := 1; run <= 2; run++ {
		if err := seed(ctx, c); err != nil {
			t.Fatal(err)
		}
		if got := codes(global); !slices.Equal(got, want) {
			t.Fatalf("run %d: global staff role: %v", run, got)
		}
		if got := codes(own); !slices.Equal(got, []string{"hrm.leave.manage"}) {
			t.Fatalf("run %d: a tenant's own role must not change: %v", run, got)
		}
		if n := c.Role.Query().Where(role.RoleCode("staff"), role.TenantIDIsNil()).CountX(ctx); n != 1 {
			t.Fatalf("run %d: %d global staff roles", run, n)
		}
		if n := c.UserRoleAssignment.Query().CountX(ctx); n != 1 {
			t.Fatalf("run %d: user assignments changed: %d", run, n)
		}
	}
	hr := c.Role.Query().Where(role.RoleCode("hr_assistant"), role.TenantIDIsNil()).OnlyX(ctx)
	if !slices.Contains(codes(hr), "hrm.leave.manage") {
		t.Fatal("HR roles keep hrm.leave.manage")
	}
}
