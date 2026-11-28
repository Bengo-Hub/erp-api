package handlers

import (
	"context"
	"net/http"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

// TestClaimLineQuantityUnitCost: a claim line keeps the quantity and unit cost that explain its
// amount, refuses an amount that is not quantity times unit cost, and a line with only an amount
// stands alone as before.
func TestClaimLineQuantityUnitCost(t *testing.T) {
	c := handlersTestClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	h := hrmRouter(tenant, NewPayrollHandler(zap.NewNop(), payroll.NewService(c, nil), nil).RegisterRoutes)
	call := func(method, path, body string) (int, map[string]any) { return selfCall(h, method, path, body, tenant) }

	emp := hrmEmployee(ctx, c, tenant, "Amina", "Otieno", "Q-1")
	claim := c.ExpenseClaim.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetAmount(decimal.Zero).SaveX(ctx)
	items := "/hrm/payroll/claims/" + claim.ID.String() + "/items"

	// Both given and matching: stored and returned.
	code, b := call(http.MethodPost, items, `{"expense_type":"ac","description":"Hotel","quantity":"3","unit_cost":"4500.50","amount":"13501.50"}`)
	if code != http.StatusCreated || b["quantity"] != "3" || b["unit_cost"] != "4500.50" || b["amount"] != "13501.50" {
		t.Fatalf("matching line: %d %v", code, b)
	}

	// Both given, amount left out: the amount is quantity times unit cost.
	code, b = call(http.MethodPost, items, `{"expense_type":"tt","description":"Bus","quantity":"2","unit_cost":"150"}`)
	if code != http.StatusCreated || b["amount"] != "300.00" || b["quantity"] != "2" || b["unit_cost"] != "150.00" {
		t.Fatalf("computed line: %d %v", code, b)
	}

	// A mismatch is refused with a message naming both figures.
	code, b = call(http.MethodPost, items, `{"expense_type":"tt","description":"Taxi","quantity":"2","unit_cost":"500","amount":"1200"}`)
	if code != http.StatusBadRequest {
		t.Fatalf("mismatch accepted: %d %v", code, b)
	}
	if msg, _ := b["error"].(string); !strings.Contains(msg, "1200.00") || !strings.Contains(msg, "1000.00") {
		t.Fatalf("mismatch message: %v", b)
	}

	// Only an amount: stands alone, no quantity or unit cost in the reply.
	code, b = call(http.MethodPost, items, `{"expense_type":"os","description":"Stationery","amount":"640"}`)
	if _, has := b["quantity"]; code != http.StatusCreated || b["amount"] != "640.00" || has {
		t.Fatalf("amount-only line: %d %v", code, b)
	}
	// Only one of the two: the amount stands alone too, and the given figure is still kept.
	code, b = call(http.MethodPost, items, `{"expense_type":"os","description":"Tolls","quantity":"4","amount":"200"}`)
	if code != http.StatusCreated || b["amount"] != "200.00" || b["quantity"] != "4" {
		t.Fatalf("quantity-only line: %d %v", code, b)
	}

	// Reload: the list returns what was saved, and the claim total is the sum of the four lines.
	code, list := call(http.MethodGet, items, "")
	rows, _ := list["data"].([]any)
	if code != http.StatusOK || len(rows) != 4 {
		t.Fatalf("claim lines: %d %v", code, list)
	}
	var hotel map[string]any
	for _, r := range rows {
		if m := r.(map[string]any); m["description"] == "Hotel" {
			hotel = m
		}
	}
	if hotel == nil || hotel["quantity"] != "3" || hotel["unit_cost"] != "4500.50" {
		t.Fatalf("line after reload: %v", rows)
	}
	if got := c.ExpenseClaim.GetX(ctx, claim.ID).Amount.StringFixed(2); got != "14641.50" {
		t.Fatalf("claim total: %s", got)
	}
}
