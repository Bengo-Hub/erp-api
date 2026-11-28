package payrollsettings

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
)

// Deduction limits follow the Employment Act (Cap. 226) s.19. Subsection (3): all deductions
// together may not exceed two thirds of the wages at any one time, unless the Minister
// prescribes otherwise. Subsection (1)(h): an employer loan repayment may not exceed half of the
// wages left after the other deductions. The statutory deductions (PAYE, NSSF, SHIF, the
// Housing Levy) are always taken first and never cut; ByLaw lists the opt-in deductions that a
// written law or court order also requires (HELB, a garnishee order), treated the same way.
// The values are data: set on the platform and overridable per tenant, kept in app settings
// under DeductionLimitsKey. A field left out inherits (tenant from platform, platform from the
// Act).
const DeductionLimitsKey = "payroll.deduction_limits"

// The Act's defaults.
var (
	ActMaxShare  = decimal.NewFromInt(2).DivRound(decimal.NewFromInt(3), 10)
	ActLoanShare = decimal.RequireFromString("0.5")
	DefaultByLaw = []string{"helb", "court_order"}
)

// DeductionLimitsDoc is one level's stored values. Shares are fractions of wages written as a
// decimal ("0.5") or a ratio ("2/3"). ByLaw holds component codes, or ids for a tenant's own
// components; an empty list replaces the inherited one.
type DeductionLimitsDoc struct {
	MaxShare  *string   `json:"max_share,omitempty"`
	LoanShare *string   `json:"loan_share,omitempty"`
	ByLaw     *[]string `json:"by_law,omitempty"`
}

// DeductionLimits are the values in force for a tenant.
type DeductionLimits struct {
	MaxShare  decimal.Decimal `json:"max_share"`
	LoanShare decimal.Decimal `json:"loan_share"`
	ByLaw     []string        `json:"by_law"`
}

// IsByLaw reports whether a component (by code, or by id for a tenant's own) is required by law.
func (l DeductionLimits) IsByLaw(code string, id uuid.UUID) bool {
	for _, c := range l.ByLaw {
		if (code != "" && c == code) || (id != uuid.Nil && c == id.String()) {
			return true
		}
	}
	return false
}

// ParseShare reads a fraction of wages: a decimal or a ratio, above 0 and at most 1.
func ParseShare(s string) (decimal.Decimal, error) {
	s = strings.TrimSpace(s)
	var v decimal.Decimal
	if num, den, ok := strings.Cut(s, "/"); ok {
		n, err1 := decimal.NewFromString(strings.TrimSpace(num))
		d, err2 := decimal.NewFromString(strings.TrimSpace(den))
		if err1 != nil || err2 != nil || !d.IsPositive() {
			return decimal.Zero, fmt.Errorf("share %q must be a decimal like 0.5 or a ratio like 2/3", s)
		}
		v = n.DivRound(d, 10)
	} else {
		var err error
		if v, err = decimal.NewFromString(s); err != nil {
			return decimal.Zero, fmt.Errorf("share %q must be a decimal like 0.5 or a ratio like 2/3", s)
		}
	}
	if !v.IsPositive() || v.GreaterThan(decimal.NewFromInt(1)) {
		return decimal.Zero, fmt.Errorf("share %q must be above 0 and at most 1", s)
	}
	return v, nil
}

// ResolveDeductionLimits applies tenant over platform over the Act. Stored values were checked
// when saved; one that no longer parses falls back to the next level.
func ResolveDeductionLimits(tenant, platform DeductionLimitsDoc) DeductionLimits {
	l := DeductionLimits{MaxShare: ActMaxShare, LoanShare: ActLoanShare, ByLaw: DefaultByLaw}
	for _, doc := range []DeductionLimitsDoc{platform, tenant} {
		if doc.MaxShare != nil {
			if v, err := ParseShare(*doc.MaxShare); err == nil {
				l.MaxShare = v
			}
		}
		if doc.LoanShare != nil {
			if v, err := ParseShare(*doc.LoanShare); err == nil {
				l.LoanShare = v
			}
		}
		if doc.ByLaw != nil {
			l.ByLaw = *doc.ByLaw
		}
	}
	return l
}

// DeductionLimitsDocFor returns a tenant's own stored values (the platform's for the platform
// tenant).
func (s *Service) DeductionLimitsDocFor(ctx context.Context, tenantID uuid.UUID) (DeductionLimitsDoc, error) {
	var doc DeductionLimitsDoc
	if tenantID == uuid.Nil {
		return doc, nil
	}
	row, err := s.orm.AppSetting.Query().Where(appsetting.TenantID(tenantID), appsetting.AppKey(DeductionLimitsKey)).Only(ctx)
	if ent.IsNotFound(err) {
		return doc, nil
	}
	if err != nil {
		return doc, err
	}
	if err := json.Unmarshal([]byte(row.Value), &doc); err != nil {
		return doc, fmt.Errorf("payroll deduction limits: %w", err)
	}
	return doc, nil
}

// DeductionLimitsFor returns the limits in force for a tenant.
func (s *Service) DeductionLimitsFor(ctx context.Context, tenantID uuid.UUID) (DeductionLimits, error) {
	platform, err := s.DeductionLimitsDocFor(ctx, s.systemTenant)
	if err != nil {
		return DeductionLimits{}, err
	}
	var own DeductionLimitsDoc
	if tenantID != s.systemTenant {
		if own, err = s.DeductionLimitsDocFor(ctx, tenantID); err != nil {
			return DeductionLimits{}, err
		}
	}
	return ResolveDeductionLimits(own, platform), nil
}

// SetDeductionLimits replaces a tenant's own values (the platform's for the platform tenant).
// A field left out inherits.
func (s *Service) SetDeductionLimits(ctx context.Context, tenantID uuid.UUID, doc DeductionLimitsDoc) (DeductionLimitsDoc, error) {
	for _, v := range []*string{doc.MaxShare, doc.LoanShare} {
		if v == nil {
			continue
		}
		if _, err := ParseShare(*v); err != nil {
			return doc, err
		}
		*v = strings.TrimSpace(*v)
	}
	if doc.ByLaw != nil {
		seen := map[string]bool{}
		clean := []string{}
		for _, c := range *doc.ByLaw {
			c = strings.TrimSpace(c)
			if c != "" && !seen[c] {
				seen[c] = true
				clean = append(clean, c)
			}
		}
		doc.ByLaw = &clean
	}
	raw, err := json.Marshal(doc)
	if err != nil {
		return doc, err
	}
	err = s.orm.AppSetting.Create().SetTenantID(tenantID).SetAppKey(DeductionLimitsKey).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).UpdateNewValues().Exec(ctx)
	return doc, err
}
