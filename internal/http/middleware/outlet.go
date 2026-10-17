package middleware

import (
	"context"
	"net/http"

	authclient "github.com/Bengo-Hub/shared-auth-client"
)

type ctxKey string

const (
	outletIDKey       ctxKey = "outlet_id"
	restrictedUserKey ctxKey = "restricted_user"
)

// OutletContext resolves outlet scoping from JWT claims + X-Outlet-ID header.
// Outlet rules:
//   - service accounts bypass outlet filtering
//   - HQ/admin (CanAccessAllOutlets): honour X-Outlet-ID for drill-down, empty = all outlets
//   - non-HQ users: pinned to their JWT outlet claim; override header ignored
func OutletContext(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		claims, hasClaims := authclient.ClaimsFromContext(ctx)
		headerOutletID := r.Header.Get("X-Outlet-ID")

		if hasClaims && claims != nil {
			if claims.IsService {
				next.ServeHTTP(w, r)
				return
			}
			if claims.CanAccessAllOutlets() {
				if headerOutletID != "" {
					ctx = context.WithValue(ctx, outletIDKey, headerOutletID)
				}
				next.ServeHTTP(w, r.WithContext(ctx))
				return
			}
			if claims.OutletID != "" {
				ctx = context.WithValue(ctx, outletIDKey, claims.OutletID)
			}
			ctx = context.WithValue(ctx, restrictedUserKey, true)
			next.ServeHTTP(w, r.WithContext(ctx))
			return
		}

		if headerOutletID != "" {
			ctx = context.WithValue(ctx, outletIDKey, headerOutletID)
		}
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// GetOutletID returns the resolved outlet ID, or "" for all-outlets/HQ mode.
func GetOutletID(ctx context.Context) string {
	v, _ := ctx.Value(outletIDKey).(string)
	return v
}

// IsRestrictedUser reports whether the user is non-HQ staff pinned to one outlet.
func IsRestrictedUser(ctx context.Context) bool {
	v, _ := ctx.Value(restrictedUserKey).(bool)
	return v
}
