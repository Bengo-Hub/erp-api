package handlers

import (
	"net/http"
	"net/http/httptest"
	"testing"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/google/uuid"

	mw "github.com/Bengo-Hub/erp-api/internal/http/middleware"
)

// TestOutletScopeViewAll: a member pinned to an outlet by their token stays on it, unless their
// role grants hrm.outlets.view_all; then the outlet filter (X-Outlet-ID) is honoured and no
// filter means every outlet, the same rule erp-ui uses to show the filter. A member limited to a
// list of outlets (outlet_ids) stays limited whatever their permissions.
func TestOutletScopeViewAll(t *testing.T) {
	tenant, home, other := uuid.New(), uuid.New(), uuid.New()
	scopeOf := func(c *authclient.Claims, header string) uuid.UUID {
		t.Helper()
		c.TenantID = tenant.String()
		var got uuid.UUID
		h := mw.OutletContext(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			s, ok := scopeFromRequest(w, r)
			if !ok {
				t.Fatalf("no scope: %d", w.(*httptest.ResponseRecorder).Code)
			}
			got = s.OutletID
		}))
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		if header != "" {
			req.Header.Set("X-Outlet-ID", header)
		}
		req = req.WithContext(authclient.ContextWithClaims(req.Context(), c))
		h.ServeHTTP(httptest.NewRecorder(), req)
		return got
	}

	pinned := func(perms ...string) *authclient.Claims {
		return &authclient.Claims{OutletID: home.String(), Permissions: perms}
	}
	if got := scopeOf(pinned(), other.String()); got != home {
		t.Fatalf("pinned member without the permission: %v", got)
	}
	if got := scopeOf(pinned(permOutletsViewAll), other.String()); got != other {
		t.Fatalf("pinned member with the permission picks an outlet: %v", got)
	}
	if got := scopeOf(pinned(permOutletsViewAll), ""); got != uuid.Nil {
		t.Fatalf("pinned member with the permission and no filter sees every outlet: %v", got)
	}
	limited := pinned(permOutletsViewAll)
	limited.OutletIDs = []string{home.String()}
	if got := scopeOf(limited, other.String()); got != home {
		t.Fatalf("a member limited to outlets stays limited: %v", got)
	}
}
