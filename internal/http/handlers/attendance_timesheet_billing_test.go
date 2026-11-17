package handlers

import (
	"net/http"
	"testing"

	"github.com/google/uuid"

	authclient "github.com/Bengo-Hub/shared-auth-client"
)

func TestTimesheetBillingCallerRules(t *testing.T) {
	tenant := uuid.New()
	reserve := "/hrm/attendance/timesheets/billing/reserve"
	ok := `{"project_id":"` + uuid.NewString() + `","from":"2026-11-01","to":"2026-11-30","billing_ref":"` + uuid.NewString() + `"}`

	// A signed-in user, even with the attendance feature, cannot bill time directly.
	signed := &authclient.Claims{TenantID: tenant.String(), SubscriptionStatus: "ACTIVE", SubscriptionFeatures: []string{"attendance"}}
	signed.Subject = uuid.NewString()
	for _, path := range []string{reserve, "/hrm/attendance/timesheets/billing/confirm", "/hrm/attendance/timesheets/billing/release"} {
		if code, _ := selfCall(selfRouter(t, nil, signed, nil), http.MethodPost, path, ok, uuid.Nil); code != http.StatusForbidden {
			t.Errorf("user on %s: %d, want 403", path, code)
		}
	}

	h := selfRouter(t, nil, serviceClaims(), nil)
	if code, _ := selfCall(h, http.MethodPost, reserve, ok, uuid.Nil); code != http.StatusBadRequest {
		t.Fatalf("service call without X-Tenant-ID: %d, want 400", code)
	}
	ref := uuid.NewString()
	for _, bad := range []string{
		`not json`,
		`{"project_id":"` + uuid.NewString() + `","from":"2026-11-01","to":"2026-11-30","billing_ref":"nope"}`,
		`{"project_id":"nope","from":"2026-11-01","to":"2026-11-30","billing_ref":"` + ref + `"}`,
		`{"project_id":"` + uuid.NewString() + `","from":"01/11/2026","to":"2026-11-30","billing_ref":"` + ref + `"}`,
	} {
		if code, _ := selfCall(h, http.MethodPost, reserve, bad, tenant); code != http.StatusBadRequest {
			t.Errorf("%s: %d, want 400", bad, code)
		}
	}
	if code, _ := selfCall(h, http.MethodPost, "/hrm/attendance/timesheets/billing/confirm",
		`{"billing_ref":"`+ref+`","invoice_id":"nope"}`, tenant); code != http.StatusBadRequest {
		t.Errorf("confirm with a bad invoice_id: %d, want 400", code)
	}
}

// Against Postgres: a reversed or too long period is 400; a valid one answers the contract shape.
func TestTimesheetBillingReserveShape(t *testing.T) {
	client := handlersTestClient(t)
	tenant := uuid.New()
	h := selfRouter(t, client, serviceClaims(), nil)
	body := func(from, to string) string {
		return `{"project_id":"` + uuid.NewString() + `","from":"` + from + `","to":"` + to + `","billing_ref":"` + uuid.NewString() + `"}`
	}
	for _, p := range [][2]string{{"2026-11-30", "2026-11-01"}, {"2026-01-01", "2027-01-03"}} {
		if code, _ := selfCall(h, http.MethodPost, "/hrm/attendance/timesheets/billing/reserve", body(p[0], p[1]), tenant); code != http.StatusBadRequest {
			t.Errorf("period %v: %d, want 400", p, code)
		}
	}
	code, out := selfCall(h, http.MethodPost, "/hrm/attendance/timesheets/billing/reserve", body("2026-11-01", "2026-11-30"), tenant)
	if code != http.StatusOK {
		t.Fatalf("reserve: %d %v", code, out)
	}
	if data, ok := out["data"].([]any); !ok || len(data) != 0 {
		t.Fatalf("data = %v, want an empty list", out["data"])
	}
	if v, ok := out["billed_invoice_id"]; !ok || v != nil {
		t.Fatalf("billed_invoice_id = %v (present %v), want null", v, ok)
	}
	code, out = selfCall(h, http.MethodPost, "/hrm/attendance/timesheets/billing/release",
		`{"billing_ref":"`+uuid.NewString()+`","include_confirmed":true}`, tenant)
	if code != http.StatusOK || out["released"] != float64(0) {
		t.Fatalf("release: %d %v", code, out)
	}
}
