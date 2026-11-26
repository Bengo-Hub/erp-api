package handlers

import (
	"context"
	"errors"
	"net/http"
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"

	authclient "github.com/Bengo-Hub/shared-auth-client"

	"github.com/Bengo-Hub/erp-api/internal/ent/userroleassignment"
	"github.com/Bengo-Hub/erp-api/internal/http/middleware"
)

// rolesAfterToken signs the user in with SSO roles, as every request does, and returns the role
// codes they hold.
func (e *grantEnv) rolesAfterToken(t *testing.T, user uuid.UUID, ssoRoles ...string) []string {
	t.Helper()
	ctx := context.Background()
	if _, err := e.svc.EnsureUserFromToken(ctx, e.tenant, user.String(), "", middleware.MapGlobalRolesToERP(ssoRoles)...); err != nil {
		t.Fatal(err)
	}
	return e.codes(t, user)
}

func (e *grantEnv) codes(t *testing.T, user uuid.UUID) []string {
	t.Helper()
	rs, err := e.svc.GetUserRoles(context.Background(), e.tenant, user)
	if err != nil {
		t.Fatal(err)
	}
	out := []string{}
	for _, r := range rs {
		out = append(out, r.RoleCode)
	}
	slices.Sort(out)
	return out
}

// TestRBACGivenRoleSurvivesSignIn: a role given in ERP stays when the person signs in with a token
// that does not carry it, while a role that came from a token still leaves with the token.
func TestRBACGivenRoleSurvivesSignIn(t *testing.T) {
	e := newGrantEnv(t)
	admin, user := e.user("erp_admin"), e.user()
	if got := e.rolesAfterToken(t, user, "cashier"); !slices.Equal(got, []string{"staff"}) {
		t.Fatalf("token role: %v", got)
	}
	if code, b := e.as(admin.String())(http.MethodPost, assignPath(user), roleIDBody(e.role["hr_manager"].ID)); code != http.StatusCreated {
		t.Fatalf("assign: %d %v", code, b)
	}
	if got := e.rolesAfterToken(t, user, "cashier"); !slices.Equal(got, []string{"hr_manager", "staff"}) {
		t.Fatalf("the given role vanished at the next sign-in: %v", got)
	}
	if got := e.rolesAfterToken(t, user); !slices.Equal(got, []string{"hr_manager"}) {
		t.Fatalf("a token without the role must remove only what a token gave: %v", got)
	}

	// Giving a role the token already carries makes it ERP-given, so it stays without the token.
	if got := e.rolesAfterToken(t, user, "hr_viewer"); !slices.Equal(got, []string{"hr_manager"}) {
		t.Fatalf("hr_viewer is not seeded in this test, nothing changes: %v", got)
	}
	if got := e.rolesAfterToken(t, user, "cashier"); !slices.Equal(got, []string{"hr_manager", "staff"}) {
		t.Fatalf("staff from the token: %v", got)
	}
	if code, b := e.as(admin.String())(http.MethodPost, assignPath(user), roleIDBody(e.role["staff"].ID)); code != http.StatusCreated {
		t.Fatalf("assign staff: %d %v", code, b)
	}
	if got := e.rolesAfterToken(t, user); !slices.Equal(got, []string{"hr_manager", "staff"}) {
		t.Fatalf("staff given in ERP must stay: %v", got)
	}
}

// fakeMembers answers membership from a set; down simulates auth-api being unreachable.
type fakeMembers struct {
	active map[string]bool
	down   bool
}

func (f *fakeMembers) ActiveMember(_ context.Context, _, userID string) (bool, error) {
	if f.down {
		return false, errors.New("auth-api unreachable")
	}
	return f.active[userID], nil
}

// TestRBACGivenRoleNeedsActiveMembership: a role given in ERP stops counting, for permissions and
// for the last-administrator rule, as soon as the person is not an active member; a role from the
// token is not checked, an expired assignment never counts, and a deactivated account loses what
// ERP gave it everywhere.
func TestRBACGivenRoleNeedsActiveMembership(t *testing.T) {
	e := newGrantEnv(t)
	ctx := context.Background()
	members := &fakeMembers{active: map[string]bool{}}
	e.svc.WithMembers(members)
	admin, user := e.user(), e.user()
	e.c.UserRoleAssignment.Create().SetTenantID(e.tenant).SetUserID(admin).SetRoleID(e.role["erp_admin"].ID).SaveX(ctx)
	members.active[admin.String()], members.active[user.String()] = true, true
	if code, b := e.as(admin.String())(http.MethodPost, assignPath(user), roleIDBody(e.role["hr_manager"].ID)); code != http.StatusCreated {
		t.Fatalf("assign: %d %v", code, b)
	}
	if got := e.rolesAfterToken(t, user, "cashier"); !slices.Equal(got, []string{"hr_manager", "staff"}) {
		t.Fatalf("active member: %v", got)
	}
	members.active[user.String()] = false
	if got := e.codes(t, user); !slices.Equal(got, []string{"staff"}) {
		t.Fatalf("removed member keeps only the token role: %v", got)
	}
	members.down, members.active[user.String()] = true, true
	if got := e.codes(t, user); !slices.Equal(got, []string{"staff"}) {
		t.Fatalf("unknown membership must not apply an ERP-given role: %v", got)
	}
	members.down = false

	// Expiry: an expired assignment gives nothing and does not count as an administrator.
	past := time.Now().Add(-time.Hour)
	second := e.user()
	members.active[second.String()] = true
	e.c.UserRoleAssignment.Create().SetTenantID(e.tenant).SetUserID(second).SetRoleID(e.role["erp_admin"].ID).SetExpiresAt(past).SaveX(ctx)
	if got := e.codes(t, second); len(got) != 0 {
		t.Fatalf("expired role applied: %v", got)
	}
	code, b := e.as(user.String(), func(c *authclient.Claims) { c.IsPlatformOwner = true })(http.MethodDelete, unassignPath(admin, e.role["erp_admin"].ID), "")
	wantRefused(t, "expired second administrator", code, http.StatusConflict, b, "last_admin")
	// An ERP-given administrator who left the company does not count either.
	e.c.UserRoleAssignment.Update().Where(userroleassignment.UserID(second)).ClearExpiresAt().SetSource("erp").ExecX(ctx)
	members.active[second.String()] = false
	code, b = e.as(user.String(), func(c *authclient.Claims) { c.IsPlatformOwner = true })(http.MethodDelete, unassignPath(admin, e.role["erp_admin"].ID), "")
	wantRefused(t, "administrator who left", code, http.StatusConflict, b, "last_admin")

	// Deactivation removes ERP-given roles in every company and leaves token roles.
	other := uuid.New()
	e.c.UserRoleAssignment.Create().SetTenantID(other).SetUserID(user).SetRoleID(e.role["staff"].ID).SetSource("erp").SaveX(ctx)
	n, err := e.svc.RevokeGiven(ctx, user.String())
	if err != nil || n != 2 {
		t.Fatalf("revoke: %d %v", n, err)
	}
	members.active[user.String()] = true
	if got := e.codes(t, user); !slices.Equal(got, []string{"staff"}) {
		t.Fatalf("after deactivation: %v", got)
	}
}
