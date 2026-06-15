// Command seed populates the erp-api RBAC catalogue: the fine-grained permission codes the
// HTTP handlers enforce, and the system roles that bundle them. It is idempotent — safe to
// re-run on every deploy (mirrors inventory-service/cmd/seed). Permissions/roles are global
// (tenant_id NULL = shared across tenants); per-tenant role assignment is done via /auth/me
// sync from auth-api JWT claims (rbac.EnsureUserFromToken).
//
// Usage:
//
//	POSTGRES_URL=postgres://... go run ./cmd/seed
package main

import (
	"context"
	"database/sql"
	"log"
	"strings"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/joho/godotenv"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/permission"
	"github.com/Bengo-Hub/erp-api/internal/ent/role"
)

// permissionCodes is the authoritative list of permission codes the handlers enforce
// (keep in sync with the perm* consts in internal/http/handlers/*).
var permissionCodes = []string{
	// HRM
	"hrm.employee.view", "hrm.employee.manage",
	"hrm.leave.view", "hrm.leave.manage", "hrm.leave.approve",
	"hrm.attendance.view", "hrm.attendance.manage",
	"hrm.recruitment.view", "hrm.recruitment.manage",
	"hrm.training.view", "hrm.training.manage",
	"hrm.appraisal.view", "hrm.appraisal.manage",
	"hrm.performance.view", "hrm.performance.manage",
	// Cross-cutting
	"approvals.view", "approvals.manage", "approvals.decide",
	"tasks.view", "tasks.manage",
	"reports.view",
	"business.view", "business.manage",
	"fx.view",
}

// roleGrants maps a system role to the permission codes it holds. "*" grants all permissions.
var roleGrants = map[string][]string{
	"erp_admin": {"*"},
	"hr_manager": {
		"hrm.employee.view", "hrm.employee.manage",
		"hrm.leave.view", "hrm.leave.manage", "hrm.leave.approve",
		"hrm.attendance.view", "hrm.attendance.manage",
		"hrm.recruitment.view", "hrm.recruitment.manage",
		"hrm.training.view", "hrm.training.manage",
		"hrm.appraisal.view", "hrm.appraisal.manage",
		"hrm.performance.view", "hrm.performance.manage",
		"approvals.view", "approvals.decide",
		"tasks.view", "tasks.manage", "reports.view", "business.view",
	},
	"payroll_manager": {
		"hrm.employee.view", "reports.view", "approvals.view", "approvals.decide",
		"business.view", "business.manage", "fx.view",
	},
	"hr_viewer": {
		"hrm.employee.view", "hrm.leave.view", "hrm.attendance.view",
		"hrm.recruitment.view", "hrm.training.view", "hrm.appraisal.view",
		"hrm.performance.view", "tasks.view", "reports.view",
	},
}

func main() {
	_ = godotenv.Load()
	// seed connects DIRECTLY to postgresql (bypasses pgbouncer) per platform convention.
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("load config: %v", err)
	}
	dsn := cfg.Postgres.MigrateDSN()
	if dsn == "" {
		dsn = "postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable"
	}

	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	defer func() { _ = sqlDB.Close() }()

	client := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, sqlDB)))
	defer func() { _ = client.Close() }()

	ctx := context.Background()
	if err := seed(ctx, client); err != nil {
		log.Fatalf("seed: %v", err)
	}
	log.Println("erp-api RBAC seed complete")
}

func seed(ctx context.Context, client *ent.Client) error {
	permIDs := map[string]string{} // code -> id (string)
	perms := make(map[string]*ent.Permission, len(permissionCodes))
	for _, code := range permissionCodes {
		p, err := upsertPermission(ctx, client, code)
		if err != nil {
			return err
		}
		perms[code] = p
		permIDs[code] = p.ID.String()
	}
	log.Printf("permissions ensured: %d", len(perms))

	allCodes := permissionCodes
	for roleCode, grants := range roleGrants {
		codes := grants
		if len(grants) == 1 && grants[0] == "*" {
			codes = allCodes
		}
		if err := upsertRoleWithPermissions(ctx, client, roleCode, codes, perms); err != nil {
			return err
		}
		log.Printf("role %q ensured with %d permissions", roleCode, len(codes))
	}
	return nil
}

func upsertPermission(ctx context.Context, client *ent.Client, code string) (*ent.Permission, error) {
	if p, err := client.Permission.Query().Where(permission.PermissionCode(code)).Only(ctx); err == nil {
		return p, nil
	} else if !ent.IsNotFound(err) {
		return nil, err
	}
	module, action := splitCode(code)
	return client.Permission.Create().
		SetPermissionCode(code).
		SetName(humanize(code)).
		SetModule(module).
		SetAction(action).
		Save(ctx)
}

func upsertRoleWithPermissions(ctx context.Context, client *ent.Client, roleCode string, codes []string, perms map[string]*ent.Permission) error {
	r, err := client.Role.Query().Where(role.RoleCodeEQ(roleCode), role.TenantIDIsNil()).Only(ctx)
	if ent.IsNotFound(err) {
		r, err = client.Role.Create().
			SetRoleCode(roleCode).
			SetName(humanize(roleCode)).
			SetIsSystemRole(true).
			Save(ctx)
	}
	if err != nil {
		return err
	}
	// Reconcile permissions: clear then re-add (idempotent).
	if _, err := r.Update().ClearPermissions().Save(ctx); err != nil {
		return err
	}
	add := make([]*ent.Permission, 0, len(codes))
	for _, c := range codes {
		if p := perms[c]; p != nil {
			add = append(add, p)
		}
	}
	_, err = r.Update().AddPermissions(add...).Save(ctx)
	return err
}

// splitCode derives (module, action) from a dotted code, e.g. "hrm.leave.approve" ->
// ("leave", "approve"); "reports.view" -> ("reports", "view").
func splitCode(code string) (module, action string) {
	parts := strings.Split(code, ".")
	if len(parts) == 0 {
		return code, "view"
	}
	action = parts[len(parts)-1]
	if len(parts) >= 2 {
		module = parts[len(parts)-2]
	} else {
		module = parts[0]
	}
	return module, action
}

// humanize turns a code into a readable label, e.g. "hrm.leave.approve" -> "Hrm Leave Approve".
func humanize(code string) string {
	s := strings.NewReplacer(".", " ", "_", " ").Replace(code)
	return strings.Title(s) //nolint:staticcheck // simple seed labels
}
