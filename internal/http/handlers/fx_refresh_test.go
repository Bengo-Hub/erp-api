package handlers

import (
	"context"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	authclient "github.com/Bengo-Hub/shared-auth-client"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/fx"
)

// TestFXRefreshCoversOnlyTheCallersCompany: a company manager refreshes its own rates, even when
// asking for all; only the platform owner refreshes every company.
func TestFXRefreshCoversOnlyTheCallersCompany(t *testing.T) {
	c := handlersTestClient(t)
	ctx := context.Background()
	mine, other := uuid.New(), uuid.New()
	for _, tn := range []uuid.UUID{mine, other} {
		c.ExchangeRateAPISettings.Create().SetTenantID(tn).SetIsActive(true).SaveX(ctx)
	}
	var mu sync.Mutex
	var fetched []string
	svc := fx.NewService(c, zap.NewNop()).WithFetcher(func(_ context.Context, st *ent.ExchangeRateAPISettings) (int, error) {
		mu.Lock()
		defer mu.Unlock()
		fetched = append(fetched, st.TenantID.String())
		return 1, nil
	})
	refresh := func(query string, edit func(*authclient.Claims)) []string {
		t.Helper()
		fetched = nil
		cl := &authclient.Claims{TenantID: mine.String()}
		cl.Subject = uuid.NewString()
		edit(cl)
		r := chi.NewRouter()
		r.Use(func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				next.ServeHTTP(w, req.WithContext(authclient.ContextWithClaims(req.Context(), cl)))
			})
		})
		NewFXHandler(zap.NewNop(), svc).RegisterRoutes(r)
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/fx/refresh"+query, strings.NewReader("")))
		if w.Code != http.StatusOK {
			t.Fatalf("refresh%s: %d %s", query, w.Code, w.Body.String())
		}
		slices.Sort(fetched)
		return fetched
	}
	manager := func(c *authclient.Claims) { c.Permissions = []string{permFxManage} }
	owner := func(c *authclient.Claims) { c.IsPlatformOwner = true }
	both := []string{mine.String(), other.String()}
	slices.Sort(both)

	if got := refresh("", manager); !slices.Equal(got, []string{mine.String()}) {
		t.Fatalf("manager: %v", got)
	}
	if got := refresh("?scope=all", manager); !slices.Equal(got, []string{mine.String()}) {
		t.Fatalf("manager asking for all: %v", got)
	}
	if got := refresh("", owner); !slices.Equal(got, []string{mine.String()}) {
		t.Fatalf("owner without scope: %v", got)
	}
	if got := refresh("?scope=all", owner); !slices.Equal(got, both) {
		t.Fatalf("owner, all companies: %v", got)
	}
}
