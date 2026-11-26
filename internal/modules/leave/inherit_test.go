package leave

import (
	"encoding/json"
	"testing"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// TestTypeOverrideKeepsOnlyChanges: a customisation holds only the values that differ from the
// platform type, applying it gives the company's values without touching the platform row, and
// sending the platform values back leaves nothing to keep.
func TestTypeOverrideKeepsOnlyChanges(t *testing.T) {
	platform := &ent.LeaveCategory{Name: "Annual Leave", Description: "Paid", IsActive: true, IsPaid: true,
		DefaultAnnualDays: decimal.NewFromInt(21), AllowCarryover: true, MaxCarryoverDays: decimal.NewFromInt(5)}
	same := CategoryInput{Name: "Annual Leave", Description: "Paid", IsActive: true, IsPaid: true,
		DefaultAnnualDays: decimal.RequireFromString("21.00"), AllowCarryover: true, MaxCarryoverDays: decimal.NewFromInt(5)}
	if o := diff(platform, same); !o.empty() {
		t.Fatalf("no change must keep nothing: %+v", o)
	}
	in := same
	in.DefaultAnnualDays = decimal.NewFromInt(24)
	in.IsActive = false
	o := diff(platform, in)
	if o.DefaultAnnualDays == nil || !o.DefaultAnnualDays.Equal(decimal.NewFromInt(24)) || o.IsActive == nil || *o.IsActive ||
		o.Description != nil || o.IsPaid != nil || o.AllowCarryover != nil || o.MaxCarryoverDays != nil {
		t.Fatalf("diff: %+v", o)
	}
	got := o.apply(platform)
	if !got.DefaultAnnualDays.Equal(decimal.NewFromInt(24)) || got.IsActive || got.Description != "Paid" || got.Name != "Annual Leave" {
		t.Fatalf("apply: %+v", got)
	}
	if !platform.DefaultAnnualDays.Equal(decimal.NewFromInt(21)) || !platform.IsActive {
		t.Fatal("apply changed the platform row")
	}
	if NameKey(" annual LEAVE") != NameKey("Annual Leave") {
		t.Fatal("names must match without case and spaces")
	}
}

// TestTypeOverrideReadsMergeRecord: a record exactly as ops/merge_inherited_settings.sql writes it
// (numeric::text days such as "24.00", booleans, an empty description) is read and applied.
func TestTypeOverrideReadsMergeRecord(t *testing.T) {
	raw := `{"7b0c9a52-1111-4f7e-9a1b-000000000001": {"description": "", "is_active": false, "is_paid": false,
		"default_annual_days": "24.00", "allow_carryover": true, "max_carryover_days": "10.50"}}`
	var m map[string]TypeOverride
	if err := json.Unmarshal([]byte(raw), &m); err != nil {
		t.Fatal(err)
	}
	o, ok := m["7b0c9a52-1111-4f7e-9a1b-000000000001"]
	if !ok {
		t.Fatalf("record: %v", m)
	}
	got := o.apply(&ent.LeaveCategory{Name: "Annual Leave", Description: "Paid", IsActive: true, IsPaid: true,
		DefaultAnnualDays: decimal.NewFromInt(21), MaxCarryoverDays: decimal.NewFromInt(5)})
	if got.Description != "" || got.IsActive || got.IsPaid || !got.AllowCarryover ||
		!got.DefaultAnnualDays.Equal(decimal.NewFromInt(24)) || !got.MaxCarryoverDays.Equal(decimal.RequireFromString("10.5")) {
		t.Fatalf("applied: %+v", got)
	}
}
