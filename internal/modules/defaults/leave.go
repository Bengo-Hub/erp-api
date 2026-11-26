package defaults

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
)

// defaultLeaveCategory is one seeded leave type.
type defaultLeaveCategory struct {
	name           string
	description    string
	annualDays     string // decimal string
	allowCarryover bool
	maxCarryover   string // decimal string (0 = none/unlimited per schema comment)
	isPaid         bool
}

// defaultLeaveCategories are sensible Kenyan statutory + common leave types. Annual leave
// (21 working days) is the only carryover-eligible default (capped at 5 days), matching the
// Employment Act minimum + common practice.
var defaultLeaveCategories = []defaultLeaveCategory{
	{"Annual Leave", "Paid annual leave (Employment Act minimum)", "21", true, "5", true},
	{"Sick Leave", "Paid sick leave (14 days full + 30 half per Employment Act)", "14", false, "0", true},
	{"Maternity Leave", "Statutory maternity leave", "90", false, "0", true},
	{"Paternity Leave", "Statutory paternity leave", "14", false, "0", true},
	{"Compassionate Leave", "Bereavement / compassionate leave", "3", false, "0", true},
	{"Study Leave", "Approved study / examination leave", "0", false, "0", true},
	{"Unpaid Leave", "Leave without pay", "0", false, "0", false},
}

// EnsureLeaveCategories idempotently creates the default leave categories for a tenant.
// Skips any category whose name already exists (the (tenant_id, name) unique index makes the
// name the natural key).
func (s *Service) EnsureLeaveCategories(ctx context.Context, tenantID uuid.UUID) error {
	// Seeded once: a tenant that has any leave type keeps what it has, so a default it renamed or
	// deleted does not come back on the next deploy.
	if any, err := s.orm.LeaveCategory.Query().Where(leavecategory.TenantID(tenantID)).Exist(ctx); err != nil || any {
		return err
	}
	for _, c := range defaultLeaveCategories {
		exists, err := s.orm.LeaveCategory.Query().
			Where(leavecategory.TenantID(tenantID), leavecategory.Name(c.name)).Exist(ctx)
		if err != nil {
			return err
		}
		if exists {
			continue
		}
		if _, err := s.orm.LeaveCategory.Create().
			SetTenantID(tenantID).
			SetName(c.name).
			SetDescription(c.description).
			SetIsActive(true).
			SetIsPaid(c.isPaid).
			SetDefaultAnnualDays(decimal.RequireFromString(c.annualDays)).
			SetAllowCarryover(c.allowCarryover).
			SetMaxCarryoverDays(decimal.RequireFromString(c.maxCarryover)).
			Save(ctx); err != nil {
			return err
		}
	}
	return nil
}
