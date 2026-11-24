package payrollsettings

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
)

// PAYEBand4From is the first payroll month on the corrected PAYE band 4 upper limit.
var PAYEBand4From = time.Date(2026, 12, 1, 0, 0, 0, 0, time.UTC)

var (
	payeBand4Old = decimal.NewFromInt(799999)
	payeBand4New = decimal.NewFromInt(800000)
)

// EnsurePAYEBand4 corrects the platform PAYE formula's band 4 upper limit from 799,999 to 800,000
// (Finance Act 2023: 32.5% on the next 300,000 above 500,000) from PAYEBand4From. It is a new
// current version that closes the previous one the day before, so months before it keep the old
// limit when re-run. Tenant versions are never touched. Idempotent: a current version without the
// old limit, or one that already starts on or after PAYEBand4From, is left alone. Returns whether
// a version was created.
func EnsurePAYEBand4(ctx context.Context, orm *ent.Client, systemTenant uuid.UUID) (bool, error) {
	cur, err := orm.PayrollFormula.Query().Where(
		payrollformula.TenantID(systemTenant), payrollformula.TypeEQ("income"),
		payrollformula.CategoryEQ("primary"), payrollformula.IsCurrent(true)).Only(ctx)
	if ent.IsNotFound(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if cur.EffectiveFrom != nil && !cur.EffectiveFrom.Before(PAYEBand4From) {
		return false, nil
	}
	s := NewService(orm, systemTenant)
	stored, err := s.FormulaItems(ctx, systemTenant, cur.ID)
	if err != nil {
		return false, err
	}
	fix := func(v decimal.Decimal) decimal.Decimal {
		if v.Equal(payeBand4Old) {
			return payeBand4New
		}
		return v
	}
	changed := false
	items := make([]FormulaItemInput, 0, len(stored))
	for _, it := range stored {
		n := FormulaItemInput{AmountFrom: fix(it.AmountFrom), AmountTo: fix(it.AmountTo),
			DeductAmount: it.DeductAmount, DeductPercentage: it.DeductPercentage}
		changed = changed || !n.AmountFrom.Equal(it.AmountFrom) || !n.AmountTo.Equal(it.AmountTo)
		items = append(items, n)
	}
	if !changed {
		return false, nil
	}
	// A superseded version covers months only from a start date; an undated one would stop
	// applying to past months, so refuse rather than rewrite history.
	if cur.EffectiveFrom == nil {
		return false, fmt.Errorf("platform PAYE formula has no effective date: set it before correcting band 4")
	}
	from := PAYEBand4From
	in := FormulaInput{
		Type: cur.Type, Category: cur.Category, Title: cur.Title, Unit: cur.Unit, EffectiveFrom: &from,
		IsCurrent: true, Progressive: cur.Progressive, PersonalRelief: cur.PersonalRelief, Items: items,
		MinimumContribution: RecordedMinimumContribution(cur), DeductionOrder: cur.DeductionOrder,
	}
	if cur.RegulatorySource != nil {
		in.RegulatorySource = *cur.RegulatorySource
	}
	split, err := s.SplitRatio(ctx, systemTenant, cur.ID)
	if err != nil {
		return false, err
	}
	if split != nil {
		emp, empr := split.EmployeePercentage, split.EmployerPercentage
		in.EmployeePercentage, in.EmployerPercentage = &emp, &empr
	}
	if _, err := s.UpsertFormula(ctx, systemTenant, in); err != nil {
		return false, err
	}
	return true, nil
}
