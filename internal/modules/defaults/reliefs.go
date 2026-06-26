package defaults

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollrelief"
)

// defaultRelief describes one KRA tax relief/exemption to seed.
//
// Schema mapping (internal/ent/schema/payroll_relief.go):
//   - type:          "Personal" | "Deductible"
//   - actual_amount: true  => relief is the lesser of (percentage * base) and fixed_limit
//                     false => relief is a flat fixed_limit amount
//   - fixed_limit:   the cap (or the flat amount when actual_amount=false)
//   - percentage:    the relief rate (e.g. 15 for 15%)
//   - is_active:     repealed/inactive reliefs seeded as false
type defaultRelief struct {
	rType        string
	title        string
	actualAmount bool
	fixedLimit   string // decimal string
	percentage   string // decimal string (whole percent, e.g. "15")
	percentOf    string // "" => leave NULL
	isActive     bool
}

// defaultReliefs is the canonical KRA personal-relief + deductible set (rates current 2024/25).
//   - Personal Relief: KES 2,400/month (also hard-applied by the PAYE engine formula).
//   - Insurance Relief: 15% of premiums, capped KES 5,000/month.
//   - Affordable Housing Relief: 15% of contributions, capped KES 9,000/month (AHL is now a
//     deduction-before-tax in the engine; this relief row documents the legacy 15% cap).
//   - Disability Exemption: KES 150,000/month tax-exempt (PWD exemption certificate).
//   - Pension Relief: contributions deductible up to KES 30,000/month (KES 360,000/year).
var defaultReliefs = []defaultRelief{
	{"Personal", "Personal Relief", false, "2400", "0", "", true},
	{"Deductible", "Insurance Relief", true, "5000", "15", "Actual", true},
	{"Deductible", "Affordable Housing Relief", true, "9000", "15", "Actual", true},
	{"Deductible", "Disability Exemption", false, "150000", "0", "", true},
	{"Deductible", "Pension Relief", true, "30000", "100", "Actual", true},
}

// EnsureReliefs idempotently seeds the default KRA reliefs for a tenant (the system tenant in
// cmd/seed-payroll, or any business tenant). Skips any relief whose title already exists for
// the tenant — so a tenant's customised relief is never overwritten.
func (s *Service) EnsureReliefs(ctx context.Context, tenantID uuid.UUID) error {
	for _, r := range defaultReliefs {
		exists, err := s.orm.PayrollRelief.Query().
			Where(payrollrelief.TenantID(tenantID), payrollrelief.Title(r.title)).Exist(ctx)
		if err != nil {
			return err
		}
		if exists {
			continue
		}
		b := s.orm.PayrollRelief.Create().
			SetTenantID(tenantID).
			SetType(r.rType).
			SetTitle(r.title).
			SetActualAmount(r.actualAmount).
			SetFixedLimit(decimal.RequireFromString(r.fixedLimit)).
			SetPercentage(decimal.RequireFromString(r.percentage)).
			SetIsActive(r.isActive)
		if r.percentOf != "" {
			b = b.SetPercentOf(r.percentOf)
		}
		if _, err := b.Save(ctx); err != nil {
			return err
		}
	}
	return nil
}

// EnsureReliefsWithClient is a convenience for callers (cmd/seed-payroll) that already hold an
// *ent.Client and only want the reliefs (not the full EnsureAll set).
func EnsureReliefsWithClient(ctx context.Context, orm *ent.Client, tenantID uuid.UUID) error {
	return (&Service{orm: orm}).EnsureReliefs(ctx, tenantID)
}
