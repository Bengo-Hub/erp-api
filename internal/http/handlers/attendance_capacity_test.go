package handlers

import (
	"net/http"
	"strings"
	"testing"

	"github.com/google/uuid"

	authclient "github.com/Bengo-Hub/shared-auth-client"
)

// The capacity read needs the tenant from a service caller, the attendance view permission from a
// signed-in one, UUID ids (at most 500) and both dates; a bad request never reaches the service.
func TestCapacityRequestRules(t *testing.T) {
	tenant := uuid.New()
	base := "/hrm/attendance/capacity?from=2026-11-16&to=2026-12-13&auth_user_ids="
	h := selfRouter(t, nil, serviceClaims(), nil)

	if code, _ := selfCall(h, http.MethodGet, base+uuid.NewString(), "", uuid.Nil); code != http.StatusBadRequest {
		t.Errorf("service call without X-Tenant-ID: %d, want 400", code)
	}
	tooMany := make([]string, 501)
	for i := range tooMany {
		tooMany[i] = uuid.NewString()
	}
	for name, path := range map[string]string{
		"bad id":      base + "nope",
		"too many":    base + strings.Join(tooMany, ","),
		"no from":     "/hrm/attendance/capacity?to=2026-12-13&auth_user_ids=" + uuid.NewString(),
		"bad to":      "/hrm/attendance/capacity?from=2026-11-16&to=13-12-2026&auth_user_ids=" + uuid.NewString(),
		"no dates":    "/hrm/attendance/capacity?auth_user_ids=" + uuid.NewString(),
		"bad id last": base + uuid.NewString() + ",x",
	} {
		if code, body := selfCall(h, http.MethodGet, path, "", tenant); code != http.StatusBadRequest {
			t.Errorf("%s: %d %v, want 400", name, code, body)
		}
	}

	// A signed-in user without the attendance view permission is refused.
	signed := &authclient.Claims{TenantID: tenant.String(), SubscriptionStatus: "ACTIVE", SubscriptionFeatures: []string{"attendance"}}
	signed.Subject = uuid.NewString()
	if code, _ := selfCall(selfRouter(t, nil, signed, nil), http.MethodGet, base+uuid.NewString(), "", uuid.Nil); code != http.StatusForbidden {
		t.Errorf("signed-in user without the permission: %d, want 403", code)
	}
}
