package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	authclient "github.com/Bengo-Hub/shared-auth-client"

	"github.com/Bengo-Hub/erp-api/internal/ent/recoveryline"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

func ownerRouter(tenant uuid.UUID, register func(chi.Router)) *httptest.Server {
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			claims := &authclient.Claims{TenantID: tenant.String(), IsPlatformOwner: true}
			next.ServeHTTP(w, req.WithContext(authclient.ContextWithClaims(req.Context(), claims)))
		})
	})
	register(r)
	return httptest.NewServer(r)
}

func doJSON(t *testing.T, method, url string, body any) (int, map[string]any) {
	t.Helper()
	raw, _ := json.Marshal(body)
	req, _ := http.NewRequest(method, url, bytes.NewReader(raw))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	out := map[string]any{}
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, out
}

// An employee loan is issued under a loan type with a number of installments, shows its balance,
// lists its payroll recoveries, and cannot be deleted once payroll has recovered from it.
func TestEmployeeLoanIssueAndRecoveries(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("L").SaveX(ctx)
	srv := ownerRouter(tenant, NewPayrollSettingsHandler(zap.NewNop(), nil, client).RegisterRoutes)
	defer srv.Close()
	base := srv.URL + "/hrm/payroll-settings"

	code, lt := doJSON(t, http.MethodPost, base+"/loan-types", map[string]any{"title": "Staff loan"})
	if code != http.StatusCreated {
		t.Fatalf("create loan type = %d %v", code, lt)
	}
	code, loan := doJSON(t, http.MethodPost, base+"/loans", map[string]any{
		"employee_id": emp.ID, "loan_type_id": lt["id"], "principal_amount": "12000", "no_of_installments": 4, "start_date": "2026-10-01",
	})
	if code != http.StatusCreated || loan["monthly_installment"] != "3000.00" || loan["balance"] != "12000.00" || loan["loan_type_id"] != lt["id"] {
		t.Fatalf("issue loan = %d %v", code, loan)
	}
	// A loan type from another tenant is refused.
	other := client.LoanType.Create().SetTenantID(uuid.New()).SetTitle("X").SaveX(ctx)
	if code, _ := doJSON(t, http.MethodPost, base+"/loans", map[string]any{
		"employee_id": emp.ID, "loan_type_id": other.ID, "principal_amount": "100", "no_of_installments": 1,
	}); code != http.StatusBadRequest {
		t.Fatalf("foreign loan type = %d, want 400", code)
	}

	loanID := uuid.MustParse(loan["id"].(string))
	slip := client.Payslip.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SaveX(ctx)
	client.RecoveryLine.Create().SetTenantID(tenant).SetPayslipID(slip.ID).SetEmployeeID(emp.ID).
		SetRecoverableType(recoveryline.RecoverableTypeLoan).SetRecoverableID(loanID).SetAmount(decimal.NewFromInt(3000)).SaveX(ctx)
	code, rec := doJSON(t, http.MethodGet, base+"/loans/"+loanID.String()+"/recoveries", nil)
	if code != http.StatusOK || rec["count"].(float64) != 1 {
		t.Fatalf("recoveries = %d %v", code, rec)
	}
	if code, _ := doJSON(t, http.MethodDelete, base+"/loans/"+loanID.String(), nil); code != http.StatusConflict {
		t.Fatalf("delete a recovered loan = %d, want 409", code)
	}
	if code, _ := doJSON(t, http.MethodDelete, base+"/loan-types/"+lt["id"].(string), nil); code != http.StatusConflict {
		t.Fatalf("delete a used loan type = %d, want 409", code)
	}
}

// Advances and losses always show a date and keep the reason they were created with.
func TestRecoverableReasonAndDate(t *testing.T) {
	client := handlersTestClient(t)
	tenant := uuid.New()
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("A").SaveX(context.Background())
	srv := ownerRouter(tenant, NewPayrollHandler(zap.NewNop(), payroll.NewService(client, nil), nil).RegisterRoutes)
	defer srv.Close()
	code, adv := doJSON(t, http.MethodPost, srv.URL+"/hrm/payroll/advances", map[string]any{
		"employee_id": emp.ID, "amount": "5000", "reason": "School fees",
	})
	if code >= 300 || adv["date"] == nil || adv["date"] == "" || adv["reason"] != "School fees" {
		t.Fatalf("create advance = %d %v", code, adv)
	}
	code, loss := doJSON(t, http.MethodPost, srv.URL+"/hrm/payroll/losses-damages", map[string]any{
		"employee_id": emp.ID, "amount": "800", "reason": "Broken till", "description": "<p>Front desk</p>", "date": "2026-10-05",
	})
	if code >= 300 || loss["reason"] != "Broken till" || loss["date"] != "2026-10-05" {
		t.Fatalf("create loss = %d %v", code, loss)
	}
}
