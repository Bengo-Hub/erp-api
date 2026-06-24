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
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

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
	"hrm.payroll.view", "hrm.payroll.manage", "hrm.payroll.process",
	// Cross-cutting
	"approvals.view", "approvals.manage", "approvals.decide",
	"tasks.view", "tasks.manage",
	"reports.view",
	"business.view", "business.manage",
	"fx.view", "fx.manage",
	// Service-level RBAC management (erp owns its roles/permissions).
	"rbac.view", "rbac.manage",
	// Tenant-scoped backups (this tenant's data only).
	"backups.view", "backups.manage",
}

// Permission bundles — composed into roles below to keep mappings consistent + readable.
var (
	hrmViewAll = []string{
		"hrm.employee.view", "hrm.leave.view", "hrm.attendance.view",
		"hrm.recruitment.view", "hrm.training.view", "hrm.appraisal.view",
		"hrm.performance.view", "hrm.payroll.view",
	}
	hrmManageAll = []string{
		"hrm.employee.view", "hrm.employee.manage",
		"hrm.leave.view", "hrm.leave.manage", "hrm.leave.approve",
		"hrm.attendance.view", "hrm.attendance.manage",
		"hrm.recruitment.view", "hrm.recruitment.manage",
		"hrm.training.view", "hrm.training.manage",
		"hrm.appraisal.view", "hrm.appraisal.manage",
		"hrm.performance.view", "hrm.performance.manage",
	}
	execOversight = []string{ // see-everything + decide, but not RBAC/backup admin
		"hrm.payroll.view", "approvals.view", "approvals.decide",
		"tasks.view", "tasks.manage", "reports.view",
		"business.view", "business.manage", "fx.view", "fx.manage",
	}
)

func bundle(parts ...[]string) []string {
	seen := map[string]bool{}
	var out []string
	for _, p := range parts {
		for _, c := range p {
			if !seen[c] {
				seen[c] = true
				out = append(out, c)
			}
		}
	}
	return out
}

// roleGrants maps an erp service role to the permission codes it holds. "*" grants all.
// Role codes mirror the GLOBAL/SSO role names auth-api issues for ERP tenants (CEO, CTO,
// ICT, finance, ops, etc.) so global->service resolution + /auth/me work, and so the
// catalogue pushed to the auth registry lets admins assign them. (Seed = source of truth.)
var roleGrants = map[string][]string{
	// Platform/admin
	"erp_admin": {"*"},
	"ceo":       bundle(hrmViewAll, hrmManageAll, execOversight, []string{"approvals.manage"}),
	"cto":       bundle([]string{"hrm.employee.view", "reports.view", "business.view", "tasks.view", "tasks.manage", "approvals.view", "rbac.view", "rbac.manage", "backups.view", "backups.manage"}),
	// ICT
	"ict_manager": bundle([]string{"hrm.employee.view", "reports.view", "business.view", "business.manage", "tasks.view", "tasks.manage", "approvals.view", "rbac.view", "rbac.manage", "backups.view", "backups.manage"}),
	"ict_officer": bundle([]string{"hrm.employee.view", "reports.view", "tasks.view", "tasks.manage", "backups.view", "rbac.view"}),
	// HR
	"hr_manager":   bundle(hrmManageAll, []string{"hrm.payroll.view", "approvals.view", "approvals.decide", "tasks.view", "tasks.manage", "reports.view", "business.view"}),
	"hr_assistant": bundle([]string{"hrm.employee.view", "hrm.leave.view", "hrm.leave.manage", "hrm.attendance.view", "hrm.attendance.manage", "hrm.recruitment.view", "hrm.recruitment.manage", "hrm.training.view", "hrm.training.manage", "tasks.view", "reports.view"}),
	"hr_viewer":    bundle(hrmViewAll, []string{"tasks.view", "reports.view"}),
	// Payroll / Finance
	"payroll_manager": bundle([]string{"hrm.employee.view", "hrm.payroll.view", "hrm.payroll.manage", "hrm.payroll.process", "reports.view", "approvals.view", "approvals.decide", "business.view", "business.manage", "fx.view", "fx.manage"}),
	"finance_manager": bundle([]string{"hrm.employee.view", "hrm.payroll.view", "hrm.payroll.manage", "hrm.payroll.process", "reports.view", "approvals.view", "approvals.decide", "business.view", "business.manage", "fx.view", "fx.manage"}),
	// Operations
	"operations_manager": bundle([]string{"hrm.employee.view", "hrm.employee.manage", "hrm.leave.view", "hrm.leave.manage", "hrm.leave.approve", "hrm.attendance.view", "hrm.attendance.manage", "tasks.view", "tasks.manage", "approvals.view", "approvals.decide", "reports.view", "business.view"}),
	// Procurement / Sales (thin in HR-scope ERP)
	"procurement_manager": bundle([]string{"hrm.employee.view", "business.view", "business.manage", "reports.view", "tasks.view", "tasks.manage", "approvals.view", "approvals.decide"}),
	"sales_manager":       bundle([]string{"hrm.employee.view", "business.view", "reports.view", "tasks.view", "tasks.manage", "approvals.view"}),
	// Admin support
	"secretary": bundle([]string{"hrm.employee.view", "hrm.leave.view", "hrm.attendance.view", "hrm.recruitment.view", "hrm.training.view", "tasks.view", "tasks.manage", "reports.view", "approvals.view"}),
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

	// Push the erp role catalogue to the auth-api registry (idempotent upsert by
	// role_code) so auth keeps a copy for assignment + global->service resolution.
	// Non-fatal: a registry hiccup must not fail the seed Job.
	if err := pushRolesToAuthRegistry(ctx, cfg.Auth.ServiceURL, cfg.Auth.APIKey); err != nil {
		log.Printf("warn: push roles to auth registry failed (non-fatal): %v", err)
	}
}

// pushRolesToAuthRegistry POSTs erp's role catalogue to auth-api POST /api/v1/s2s/roles/sync.
// Idempotent on the auth side (upsert by unique role_code) — safe to call every deploy.
func pushRolesToAuthRegistry(ctx context.Context, authURL, apiKey string) error {
	authURL = strings.TrimRight(strings.TrimSpace(authURL), "/")
	if authURL == "" || strings.TrimSpace(apiKey) == "" {
		log.Println("skip role-registry push: AUTH_SERVICE_URL or INTERNAL_SERVICE_KEY unset")
		return nil
	}
	type roleEntry struct {
		RoleCode    string `json:"role_code"`
		Name        string `json:"name"`
		Description string `json:"description"`
		Scope       string `json:"scope"`
	}
	roles := make([]roleEntry, 0, len(roleGrants))
	for code := range roleGrants {
		roles = append(roles, roleEntry{RoleCode: code, Name: humanize(code), Scope: "erp"})
	}
	body, _ := json.Marshal(map[string]any{"service": "erp", "roles": roles})

	reqCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, authURL+"/api/v1/s2s/roles/sync", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", apiKey)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("auth registry returned %d", resp.StatusCode)
	}
	log.Printf("pushed %d erp roles to auth registry", len(roles))
	return nil
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
