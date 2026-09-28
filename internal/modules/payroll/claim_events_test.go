package payroll

import (
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// treasury's claim subscribers decode these keys (claimApprovedPayload and the commitment
// handler); renaming one silently drops the posting or the commitment.
func TestClaimPayloadCarriesTreasuryKeys(t *testing.T) {
	proj, cc := uuid.New(), uuid.New()
	day := time.Date(2026, 9, 28, 0, 0, 0, 0, time.UTC)
	c := &ent.ExpenseClaim{
		ID: uuid.New(), TenantID: uuid.New(), EmployeeID: uuid.New(),
		Amount: decimal.RequireFromString("1234.5"), ClaimType: "per_diem", Category: "travel",
		ProjectID: &proj, CostCenterID: &cc, ApplicationDate: &day,
	}
	p := claimPayload(c)
	want := map[string]any{
		"claim_id": c.ID.String(), "tenant_id": c.TenantID.String(), "employee_id": c.EmployeeID.String(),
		"amount": "1234.50", "currency": "KES", "claim_type": "per_diem", "taxable": false,
		"project_id": proj.String(), "cost_center_id": cc.String(), "approved": false,
		"application_date": "2026-09-28",
	}
	for k, v := range want {
		if p[k] != v {
			t.Errorf("%s = %v, want %v", k, p[k], v)
		}
	}
	bare := claimPayload(&ent.ExpenseClaim{ID: uuid.New(), TenantID: uuid.New(), Amount: decimal.Zero})
	if bare["project_id"] != "" || bare["cost_center_id"] != nil || bare["application_date"] != nil {
		t.Errorf("optional dimensions must be empty or absent: %v", bare)
	}
}
