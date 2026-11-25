package handlers

import (
	"context"
	"net/http"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	authclient "github.com/Bengo-Hub/shared-auth-client"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/userroleassignment"
	"github.com/Bengo-Hub/erp-api/internal/modules/rbac"
)

// TestRBACRoutesAreTenantScoped: a tenant with rbac.manage edits only its own roles. Global roles
// are read-only (403) except to the platform owner, another tenant's role is 404, and a role or
// user of another tenant cannot be used in an assignment.
func TestRBACRoutesAreTenantScoped(t *testing.T) {
	c := handlersTestClient(t)
	ctx := context.Background()
	a, b := uuid.New(), uuid.New()
	as := func(cl *authclient.Claims) func(method, path, body string) (int, map[string]any) {
		r := chi.NewRouter()
		r.Use(func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				next.ServeHTTP(w, req.WithContext(authclient.ContextWithClaims(req.Context(), cl)))
			})
		})
		NewRBACHandler(zap.NewNop(), rbac.NewService(c, zap.NewNop())).RegisterRoutes(r)
		return func(method, path, body string) (int, map[string]any) {
			return selfCall(r, method, path, body, uuid.Nil)
		}
	}
	tenantA := as(&authclient.Claims{TenantID: a.String(), Permissions: []string{"rbac.view", "rbac.manage"}})
	owner := as(&authclient.Claims{TenantID: a.String(), IsPlatformOwner: true})

	var codes []*ent.Permission
	for _, code := range []string{"hrm.leave.view", "hrm.leave.manage"} {
		codes = append(codes, c.Permission.Create().SetPermissionCode(code).SetName(code).SetModule("leave").SetAction("x").SaveX(ctx))
	}
	global := c.Role.Create().SetRoleCode("staff").SetName("Staff").SetIsSystemRole(true).AddPermissions(codes[0]).SaveX(ctx)
	// A global row that lost its system flag is still not a tenant's to edit.
	loose := c.Role.Create().SetRoleCode("loose").SetName("Loose").SetIsSystemRole(false).AddPermissions(codes[0]).SaveX(ctx)
	admin := c.Role.Create().SetRoleCode("erp_admin").SetName("Admin").SetIsSystemRole(true).SaveX(ctx)
	other := c.Role.Create().SetTenantID(b).SetRoleCode("clerk").SetName("B clerk").AddPermissions(codes[0]).SaveX(ctx)
	own := c.Role.Create().SetTenantID(a).SetRoleCode("clerk").SetName("A clerk").AddPermissions(codes[0]).SaveX(ctx)
	user := func(tenant uuid.UUID) uuid.UUID {
		id := uuid.New()
		c.CustomUser.Create().SetID(id).SetTenantID(tenant).SetExternalID(id.String()).SetEmail(id.String() + "@example.com").SaveX(ctx)
		return id
	}
	ua, ub := user(a), user(b)
	c.UserRoleAssignment.Create().SetTenantID(b).SetUserID(ub).SetRoleID(other.ID).SaveX(ctx)

	granted := func(r *ent.Role) int { return r.QueryPermissions().CountX(ctx) }
	const manage = `{"permission_codes":["hrm.leave.view","hrm.leave.manage"]}`
	for _, tc := range []struct {
		name string
		role *ent.Role
		want int
	}{{"global", global, http.StatusForbidden}, {"global without the system flag", loose, http.StatusForbidden}, {"other tenant", other, http.StatusNotFound}} {
		path := "/rbac/roles/" + tc.role.ID.String()
		for _, call := range []struct{ method, path, body string }{
			{http.MethodPut, path + "/permissions", manage},
			{http.MethodPut, path + "/permissions", `{"permission_codes":[]}`},
			{http.MethodPut, path, `{"name":"Hacked"}`},
			{http.MethodDelete, path, ""},
		} {
			if code, body := tenantA(call.method, call.path, call.body); code != tc.want || body["error"] == nil {
				t.Errorf("%s: %s %s: want %d, got %d %v", tc.name, call.method, call.path, tc.want, code, body)
			}
		}
		row, err := c.Role.Get(ctx, tc.role.ID)
		if err != nil || row.Name != tc.role.Name || granted(tc.role) != 1 {
			t.Errorf("%s: the role changed: %v %v, %d codes", tc.name, row, err, granted(tc.role))
		}
	}
	if n := c.UserRoleAssignment.Query().Where(userroleassignment.TenantID(b)).CountX(ctx); n != 1 {
		t.Errorf("tenant B's assignment is gone")
	}
	if code, _ := tenantA(http.MethodGet, "/rbac/roles/"+other.ID.String(), ""); code != http.StatusNotFound {
		t.Errorf("reading another tenant's role: %d", code)
	}

	// Assignments: the role and the user must be the tenant's (or a global role).
	assign := func(u, r uuid.UUID) int {
		code, _ := tenantA(http.MethodPost, "/rbac/users/"+u.String()+"/roles", `{"role_id":"`+r.String()+`"}`)
		return code
	}
	if code := assign(ua, other.ID); code != http.StatusNotFound {
		t.Errorf("assigning another tenant's role: %d", code)
	}
	if code := assign(ub, own.ID); code != http.StatusNotFound {
		t.Errorf("assigning to another tenant's user: %d", code)
	}
	if code := assign(ua, uuid.New()); code != http.StatusNotFound {
		t.Errorf("assigning an unknown role: %d", code)
	}
	if code := assign(ua, own.ID); code != http.StatusCreated {
		t.Errorf("assigning the tenant's own role: %d", code)
	}
	if code := assign(ua, global.ID); code != http.StatusCreated {
		t.Errorf("assigning a global role: %d", code)
	}
	if code, _ := tenantA(http.MethodDelete, "/rbac/users/"+ub.String()+"/roles/"+other.ID.String(), ""); code != http.StatusNoContent {
		t.Errorf("removing is a no-op in another tenant: %d", code)
	}
	if n := c.UserRoleAssignment.Query().Where(userroleassignment.TenantID(b)).CountX(ctx); n != 1 {
		t.Errorf("tenant B's assignment is gone after remove")
	}
	if code, _ := tenantA(http.MethodDelete, "/rbac/users/"+ua.String()+"/roles/"+global.ID.String(), ""); code != http.StatusNoContent {
		t.Errorf("removing an own assignment: %d", code)
	}

	// The tenant's own role works.
	path := "/rbac/roles/" + own.ID.String()
	if code, body := tenantA(http.MethodPut, path+"/permissions", manage); code != http.StatusOK || granted(own) != 2 {
		t.Errorf("own permissions: %d %v", code, body)
	}
	if code, body := tenantA(http.MethodPut, path, `{"name":"Clerks"}`); code != http.StatusOK || body["name"] != "Clerks" {
		t.Errorf("own rename: %d %v", code, body)
	}
	if code, body := tenantA(http.MethodDelete, path, ""); code != http.StatusNoContent {
		t.Errorf("own delete: %d %v", code, body)
	}

	// The platform owner edits a global role, but not the all-access one, and system roles are
	// never deleted. Another tenant's role is still 404 outside that tenant.
	gp := "/rbac/roles/" + global.ID.String()
	if code, body := owner(http.MethodPut, gp+"/permissions", manage); code != http.StatusOK || granted(global) != 2 {
		t.Errorf("platform owner, global permissions: %d %v", code, body)
	}
	if code, body := owner(http.MethodPut, gp, `{"name":"Staff member"}`); code != http.StatusOK {
		t.Errorf("platform owner, global rename: %d %v", code, body)
	}
	if code, _ := owner(http.MethodDelete, gp, ""); code != http.StatusForbidden {
		t.Errorf("platform owner deleting a system role: %d", code)
	}
	if code, _ := owner(http.MethodPut, "/rbac/roles/"+admin.ID.String()+"/permissions", manage); code != http.StatusForbidden {
		t.Errorf("all-access role: %d", code)
	}
	if code, _ := owner(http.MethodPut, "/rbac/roles/"+other.ID.String()+"/permissions", manage); code != http.StatusNotFound {
		t.Errorf("platform owner outside the tenant: %d", code)
	}
}
