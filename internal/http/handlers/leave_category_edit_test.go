package handlers

import (
	"context"
	"net/http"
	"testing"

	"github.com/shopspring/decimal"
)

// TestLeaveTypeEditKeepsUnsentFields: the edit form sends name, days, paid and carry forward only;
// the carryover cap and the active flag it does not send stay as they were.
func TestLeaveTypeEditKeepsUnsentFields(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	hr := e.hr(e.tenant)
	cat := e.c.LeaveCategory.Create().SetTenantID(e.tenant).SetName("Annual").SetIsActive(false).SetDescription("Yearly").
		SetAllowCarryover(true).SetMaxCarryoverDays(decimal.NewFromInt(5)).SetDefaultAnnualDays(decimal.NewFromInt(21)).SaveX(ctx)
	code, b := hr(http.MethodPut, "/hrm/leave/categories/"+cat.ID.String(), `{"name":"Annual Leave","max_days":"24","is_paid":true,"carry_forward":true}`)
	if code != http.StatusOK {
		t.Fatalf("edit: %d %v", code, b)
	}
	got := e.c.LeaveCategory.GetX(ctx, cat.ID)
	if got.Name != "Annual Leave" || !got.DefaultAnnualDays.Equal(decimal.NewFromInt(24)) || got.IsActive || got.Description != "Yearly" ||
		!got.MaxCarryoverDays.Equal(decimal.NewFromInt(5)) || !got.AllowCarryover {
		t.Fatalf("after edit: %+v", got)
	}
	// Sent explicitly, they change.
	if code, b := hr(http.MethodPut, "/hrm/leave/categories/"+cat.ID.String(), `{"name":"Annual Leave","is_active":true,"max_carryover_days":"0","carry_forward":false}`); code != http.StatusOK {
		t.Fatalf("edit: %d %v", code, b)
	}
	got = e.c.LeaveCategory.GetX(ctx, cat.ID)
	if !got.IsActive || !got.MaxCarryoverDays.IsZero() || got.AllowCarryover || !got.DefaultAnnualDays.Equal(decimal.NewFromInt(24)) {
		t.Fatalf("after second edit: %+v", got)
	}
}
