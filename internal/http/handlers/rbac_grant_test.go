package handlers

import (
	"context"
	"net/http"
	"slices"
	"sync"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	authclient "github.com/Bengo-Hub/shared-auth-client"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/role"
	"github.com/Bengo-Hub/erp-api/internal/ent/userroleassignment"
	"github.com/Bengo-Hub/erp-api/internal/http/middleware"
	"github.com/Bengo-Hub/erp-api/internal/modules/rbac"
)

// grantEnv has the shared roles and serves the RBAC routes as any caller, permissions coming from
// the caller's local roles as in production.
type grantEnv struct {
	c      *ent.Client
	tenant uuid.UUID
	svc    *rbac.Service
	perm   map[string]*ent.Permission
	role   map[string]*ent.Role
}

func newGrantEnv(t *testing.T) *grantEnv {
	t.Helper()
	ctx := context.Background()
	e := &grantEnv{c: handlersTestClient(t), tenant: uuid.New(), perm: map[string]*ent.Permission{}, role: map[string]*ent.Role{}}
	e.svc = rbac.NewService(e.c, zap.NewNop())
	prev := rbacService
	SetRBACService(e.svc)
	t.Cleanup(func() { rbacService = prev })
	for _, code := range []string{"rbac.view", "rbac.manage", "hrm.leave.view", "hrm.leave.manage", "hrm.payroll.disburse"} {
		e.perm[code] = e.c.Permission.Create().SetPermissionCode(code).SetName(code).SetModule("m").SetAction("a").SaveX(ctx)
	}
	for code, grants := range map[string][]string{
		"erp_admin":   {"rbac.view", "rbac.manage", "hrm.leave.view", "hrm.leave.manage", "hrm.payroll.disburse"},
		"ict_manager": {"rbac.view", "rbac.manage", "hrm.leave.view"},
		"hr_manager":  {"hrm.leave.view", "hrm.leave.manage"},
		"staff":       {"hrm.leave.view"},
	} {
		b := e.c.Role.Create().SetRoleCode(code).SetName(code).SetIsSystemRole(true)
		for _, g := range grants {
			b = b.AddPermissions(e.perm[g])
		}
		e.role[code] = b.SaveX(ctx)
	}
	return e
}

// user adds a tenant user holding the given shared roles.
func (e *grantEnv) user(roles ...string) uuid.UUID {
	ctx := context.Background()
	id := uuid.New()
	e.c.CustomUser.Create().SetID(id).SetTenantID(e.tenant).SetExternalID(id.String()).SetEmail(id.String() + "@example.com").SaveX(ctx)
	for _, r := range roles {
		e.c.UserRoleAssignment.Create().SetTenantID(e.tenant).SetUserID(id).SetRoleID(e.role[r].ID).SaveX(ctx)
	}
	return id
}

func (e *grantEnv) as(subject string, edit ...func(*authclient.Claims)) leaveCall {
	cl := &authclient.Claims{TenantID: e.tenant.String()}
	cl.Subject = subject
	for _, f := range edit {
		f(cl)
	}
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			next.ServeHTTP(w, req.WithContext(authclient.ContextWithClaims(req.Context(), cl)))
		})
	})
	NewRBACHandler(zap.NewNop(), e.svc).RegisterRoutes(r)
	return func(method, path, body string) (int, map[string]any) {
		return selfCall(r, method, path, body, uuid.Nil)
	}
}

func assignPath(u uuid.UUID) string      { return "/rbac/users/" + u.String() + "/roles" }
func roleIDBody(r uuid.UUID) string      { return `{"role_id":"` + r.String() + `"}` }
func unassignPath(u, r uuid.UUID) string { return assignPath(u) + "/" + r.String() }
func wantRefused(t *testing.T, what string, code, wantCode int, body map[string]any, wantKind string) {
	t.Helper()
	if code != wantCode || body["code"] != wantKind || body["error"] == nil {
		t.Errorf("%s: want %d %s, got %d %v", what, wantCode, wantKind, code, body)
	}
}

// TestRBACNobodyGrantsBeyondTheirOwn: roles and permissions handed out never exceed what the
// caller holds; erp_admin and the platform owner are exempt.
func TestRBACNobodyGrantsBeyondTheirOwn(t *testing.T) {
	e := newGrantEnv(t)
	ctx := context.Background()
	ict, admin, target := e.user("ict_manager"), e.user("erp_admin"), e.user()
	asICT, asAdmin := e.as(ict.String()), e.as(admin.String())

	// Assigning: hr_manager holds more than ict_manager, staff does not.
	code, b := asICT(http.MethodPost, assignPath(target), roleIDBody(e.role["hr_manager"].ID))
	wantRefused(t, "hr_manager by ict_manager", code, http.StatusForbidden, b, "beyond_own_permissions")
	if b["error"] != "you can only give permissions you hold yourself; you do not hold hrm.leave.manage" {
		t.Errorf("reason: %v", b)
	}
	code, b = asICT(http.MethodPost, assignPath(target), roleIDBody(e.role["erp_admin"].ID))
	wantRefused(t, "erp_admin by ict_manager", code, http.StatusForbidden, b, "beyond_own_permissions")
	if code, b := asICT(http.MethodPost, assignPath(target), roleIDBody(e.role["staff"].ID)); code != http.StatusCreated {
		t.Errorf("staff by ict_manager: %d %v", code, b)
	}
	// Even someone holding every code of erp_admin cannot give it, since the role means more.
	everything := func(c *authclient.Claims) {
		for p := range e.perm {
			c.Permissions = append(c.Permissions, p)
		}
	}
	code, b = e.as(e.user().String(), everything)(http.MethodPost, assignPath(target), roleIDBody(e.role["erp_admin"].ID))
	wantRefused(t, "erp_admin by a holder of every code", code, http.StatusForbidden, b, "beyond_own_permissions")
	// A service key acts for nobody's role, so it cannot make administrators either.
	code, b = e.as("", func(c *authclient.Claims) { c.IsService = true })(http.MethodPost, assignPath(target), roleIDBody(e.role["erp_admin"].ID))
	wantRefused(t, "erp_admin by a service", code, http.StatusForbidden, b, "beyond_own_permissions")

	// Role permissions: only held codes can be added, existing ones may stay, removing is free.
	own := e.c.Role.Create().SetTenantID(e.tenant).SetRoleCode("clerk").SetName("Clerk").AddPermissions(e.perm["hrm.payroll.disburse"]).SaveX(ctx)
	path := "/rbac/roles/" + own.ID.String() + "/permissions"
	code, b = asICT(http.MethodPut, path, `{"permission_codes":["hrm.payroll.disburse","hrm.leave.manage"]}`)
	wantRefused(t, "adding an unheld code", code, http.StatusForbidden, b, "beyond_own_permissions")
	if n := own.QueryPermissions().CountX(ctx); n != 1 {
		t.Errorf("a refused change must save nothing: %d codes", n)
	}
	if code, b := asICT(http.MethodPut, path, `{"permission_codes":["hrm.payroll.disburse","hrm.leave.view"]}`); code != http.StatusOK || own.QueryPermissions().CountX(ctx) != 2 {
		t.Errorf("keeping an existing code: %d %v", code, b)
	}
	// And such a role cannot be assigned by someone who lacks one of its codes.
	code, b = asICT(http.MethodPost, assignPath(target), roleIDBody(own.ID))
	wantRefused(t, "assigning a custom role with an unheld code", code, http.StatusForbidden, b, "beyond_own_permissions")
	if code, b := asICT(http.MethodPut, path, `{"permission_codes":["hrm.leave.view"]}`); code != http.StatusOK {
		t.Errorf("removing a code: %d %v", code, b)
	}
	code, b = asICT(http.MethodPut, path, `{"permission_codes":["hrm.leave.view","hrm.payroll.disburse"]}`)
	wantRefused(t, "putting a removed code back", code, http.StatusForbidden, b, "beyond_own_permissions")

	// erp_admin and the platform owner are exempt.
	if code, b := asAdmin(http.MethodPut, path, `{"permission_codes":["hrm.payroll.disburse"]}`); code != http.StatusOK {
		t.Errorf("admin permissions: %d %v", code, b)
	}
	if code, b := asAdmin(http.MethodPost, assignPath(target), roleIDBody(e.role["erp_admin"].ID)); code != http.StatusCreated {
		t.Errorf("admin gives admin: %d %v", code, b)
	}
	owner := e.as(uuid.NewString(), func(c *authclient.Claims) { c.IsPlatformOwner = true })
	if code, b := owner(http.MethodPost, assignPath(e.user()), roleIDBody(e.role["hr_manager"].ID)); code != http.StatusCreated {
		t.Errorf("platform owner: %d %v", code, b)
	}
}

// TestRBACNobodyChangesTheirOwnRoles: assigning to or removing from oneself is refused for every
// caller, administrators and the platform owner included, also when the user row carries the
// token's id only as external_id.
func TestRBACNobodyChangesTheirOwnRoles(t *testing.T) {
	e := newGrantEnv(t)
	ctx := context.Background()
	e.user("erp_admin")
	admin, ict := e.user("erp_admin"), e.user("ict_manager")
	ownerFlag := func(c *authclient.Claims) { c.IsPlatformOwner = true }
	for name, call := range map[string]leaveCall{
		"administrator":  e.as(admin.String()),
		"platform owner": e.as(admin.String(), ownerFlag),
	} {
		code, b := call(http.MethodPost, assignPath(admin), roleIDBody(e.role["staff"].ID))
		wantRefused(t, name+" assigning to self", code, http.StatusForbidden, b, "own_roles")
		code, b = call(http.MethodDelete, unassignPath(admin, e.role["erp_admin"].ID), "")
		wantRefused(t, name+" removing from self", code, http.StatusForbidden, b, "own_roles")
	}
	code, b := e.as(ict.String())(http.MethodPost, assignPath(ict), roleIDBody(e.role["staff"].ID))
	wantRefused(t, "ict_manager assigning to self", code, http.StatusForbidden, b, "own_roles")

	subject := uuid.NewString()
	legacy := e.c.CustomUser.Create().SetTenantID(e.tenant).SetExternalID(subject).SetEmail("l@example.com").SaveX(ctx)
	manage := func(c *authclient.Claims) { c.Permissions = []string{"rbac.manage", "hrm.leave.view"} }
	code, b = e.as(subject, manage)(http.MethodPost, assignPath(legacy.ID), roleIDBody(e.role["staff"].ID))
	wantRefused(t, "self by external id", code, http.StatusForbidden, b, "own_roles")

	// Deleting a custom role one holds would change one's own roles.
	held := e.c.Role.Create().SetTenantID(e.tenant).SetRoleCode("clerk").SetName("Clerk").SaveX(ctx)
	e.c.UserRoleAssignment.Create().SetTenantID(e.tenant).SetUserID(ict).SetRoleID(held.ID).SaveX(ctx)
	code, b = e.as(ict.String())(http.MethodDelete, "/rbac/roles/"+held.ID.String(), "")
	wantRefused(t, "deleting a role one holds", code, http.StatusForbidden, b, "own_roles")
	if code, b := e.as(admin.String())(http.MethodDelete, "/rbac/roles/"+held.ID.String(), ""); code != http.StatusNoContent {
		t.Errorf("someone else deletes it: %d %v", code, b)
	}
}

// TestRBACLastAdministratorStays: a company keeps at least one erp_admin, also when two
// administrators remove each other at the same moment. Other tenants do not count.
func TestRBACLastAdministratorStays(t *testing.T) {
	e := newGrantEnv(t)
	ctx := context.Background()
	other := uuid.New()
	e.c.CustomUser.Create().SetID(other).SetTenantID(uuid.New()).SetExternalID(other.String()).SetEmail("o@example.com").SaveX(ctx)
	e.c.UserRoleAssignment.Create().SetTenantID(uuid.New()).SetUserID(other).SetRoleID(e.role["erp_admin"].ID).SaveX(ctx)
	ict, last := e.user("ict_manager"), e.user("erp_admin")
	code, b := e.as(ict.String())(http.MethodDelete, unassignPath(last, e.role["erp_admin"].ID), "")
	wantRefused(t, "last administrator", code, http.StatusConflict, b, "last_admin")
	// Their other roles may go.
	e.c.UserRoleAssignment.Create().SetTenantID(e.tenant).SetUserID(last).SetRoleID(e.role["staff"].ID).SaveX(ctx)
	if code, b := e.as(ict.String())(http.MethodDelete, unassignPath(last, e.role["staff"].ID), ""); code != http.StatusNoContent {
		t.Errorf("other role of the last administrator: %d %v", code, b)
	}

	second := e.user("erp_admin")
	pair := [2]uuid.UUID{last, second}
	var wg sync.WaitGroup
	codes := make([]int, 2)
	for i := range pair {
		wg.Add(1)
		call := e.as(pair[i].String())
		go func() {
			defer wg.Done()
			codes[i], _ = call(http.MethodDelete, unassignPath(pair[1-i], e.role["erp_admin"].ID), "")
		}()
	}
	wg.Wait()
	slices.Sort(codes)
	if n := e.c.UserRoleAssignment.Query().Where(userroleassignment.TenantID(e.tenant), userroleassignment.RoleID(e.role["erp_admin"].ID)).CountX(ctx); n != 1 || codes[0] != http.StatusNoContent || codes[1] == http.StatusNoContent {
		t.Errorf("mutual removal must leave one administrator: %d left, %v", n, codes)
	}
}

// TestRBACBuiltInCodes: a custom role cannot take a built-in code on create or rename, and a
// custom row that has one anyway never stands in for the shared role during SSO sync.
func TestRBACBuiltInCodes(t *testing.T) {
	e := newGrantEnv(t)
	ctx := context.Background()
	call := e.as(e.user("ict_manager").String())
	for _, body := range []string{
		`{"role_code":"staff","name":"X"}`, `{"role_code":"  ERP_Admin ","name":"X"}`,
		`{"role_code":"secretary","name":"X"}`, `{"role_code":"mine","name":" Staff "}`,
	} {
		code, b := call(http.MethodPost, "/rbac/roles", body)
		wantRefused(t, "create "+body, code, http.StatusBadRequest, b, "built_in_code")
	}
	code, made := call(http.MethodPost, "/rbac/roles", `{"role_code":" clerk ","name":"Clerk"}`)
	if code != http.StatusCreated || made["role_code"] != "clerk" {
		t.Fatalf("create: %d %v", code, made)
	}
	code, b := call(http.MethodPut, "/rbac/roles/"+made["id"].(string), `{"name":"HR_Manager"}`)
	wantRefused(t, "rename", code, http.StatusBadRequest, b, "built_in_code")
	if code, b := call(http.MethodPut, "/rbac/roles/"+made["id"].(string), `{"name":"Senior clerk"}`); code != http.StatusOK {
		t.Errorf("rename: %d %v", code, b)
	}

	// A shadowing row made before the rule: sync resolves to the shared role.
	shadow := e.c.Role.Create().SetTenantID(e.tenant).SetRoleCode("staff").SetName("Shadow").AddPermissions(e.perm["hrm.payroll.disburse"]).SaveX(ctx)
	subject := uuid.NewString()
	sync := func(roles ...string) []string {
		t.Helper()
		u, err := e.svc.EnsureUserFromToken(ctx, e.tenant, subject, "s@example.com", middleware.MapGlobalRolesToERP(roles)...)
		if err != nil {
			t.Fatal(err)
		}
		rs, err := e.svc.GetUserRoles(ctx, e.tenant, u.ID)
		if err != nil {
			t.Fatal(err)
		}
		var out []string
		for _, r := range rs {
			if r.ID == shadow.ID {
				t.Errorf("sync used the tenant's shadow of a built-in role")
			}
			out = append(out, r.RoleCode)
		}
		slices.Sort(out)
		return out
	}
	// Sync follows auth-api in both directions and is not held to the caller rules, so a person's
	// first administrator role arrives and leaves with the token, the last one included.
	if got := sync("cashier"); !slices.Equal(got, []string{"staff"}) {
		t.Errorf("sync to staff: %v", got)
	}
	if got := sync("admin", "hr_manager"); !slices.Equal(got, []string{"erp_admin", "hr_manager"}) {
		t.Errorf("sync to admin: %v", got)
	}
	if got := sync("hr_manager"); !slices.Equal(got, []string{"hr_manager"}) {
		t.Errorf("sync away from admin: %v", got)
	}
	// A code that is not built in still prefers the tenant's own role, and a missing shared row
	// is not replaced by a tenant's.
	e.c.UserRoleAssignment.Delete().Where(userroleassignment.RoleID(e.role["hr_manager"].ID)).ExecX(ctx)
	e.c.Role.UpdateOne(e.role["hr_manager"]).ClearPermissions().ExecX(ctx)
	e.c.Role.Delete().Where(role.ID(e.role["hr_manager"].ID)).ExecX(ctx)
	e.c.Role.Create().SetTenantID(e.tenant).SetRoleCode("hr_manager").SetName("Fake").SaveX(ctx)
	if got := sync("hr_manager"); len(got) != 0 {
		t.Errorf("a tenant row replaced a missing shared role: %v", got)
	}
}
