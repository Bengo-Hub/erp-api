package payrollsettings

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

// Treasury rate sync.
//
// treasury-api keeps the platform-wide Kenya statutory rate reference. A rate enters it only when
// the platform owner creates it or approves a tax advisor proposal, and its S2S list returns only
// the rates in force. The sync maps that reference onto the PLATFORM payroll formulas (never a
// tenant's own version) and applies a change only when treasury's rate set is both newer (a later
// effective date than the platform formula) and different, so restating the same law in another
// shape never churns the verified platform formulas. An applied change becomes a new current
// platform version from treasury's effective date; the previous version is closed the day before,
// so earlier months still compute on the old rates.

// treasuryFormula is treasury's rate set for one platform formula.
type treasuryFormula struct {
	ftype, category string
	effectiveFrom   time.Time
	source          string
	items           []FormulaItemInput
	personalRelief  *decimal.Decimal
	// reliefFrom is when the personal relief took effect. It moves the version date only when
	// the relief itself changed (bands and relief are separate provisions).
	reliefFrom time.Time
}

// versionDate is the effective date of treasury's rate set given the platform's current relief.
func (tf treasuryFormula) versionDate(currentRelief decimal.Decimal) time.Time {
	if tf.personalRelief != nil && !tf.personalRelief.Equal(currentRelief) && tf.reliefFrom.After(tf.effectiveFrom) {
		return tf.reliefFrom
	}
	return tf.effectiveFrom
}

// mapTreasuryRates groups treasury's in-force rates into formula rate sets: PAYE bands and the
// personal relief, NSSF tiers, SHIF and the housing levy. Rows of other categories are ignored.
func mapTreasuryRates(rates []treasury.StatutoryRate) []treasuryFormula {
	byCat := map[string][]treasury.StatutoryRate{}
	for _, r := range rates {
		if !r.IsActive {
			continue
		}
		byCat[strings.ToLower(r.Category)] = append(byCat[strings.ToLower(r.Category)], r)
	}
	var out []treasuryFormula

	// PAYE: PAYE_BAND_* rows are the brackets; PAYE_PERSONAL_RELIEF is the monthly relief.
	var bands []treasury.StatutoryRate
	var relief *treasury.StatutoryRate
	for i, r := range byCat["paye"] {
		switch {
		case strings.HasPrefix(strings.ToUpper(r.Code), "PAYE_BAND"):
			bands = append(bands, r)
		case strings.Contains(strings.ToUpper(r.Code), "PERSONAL_RELIEF"):
			relief = &byCat["paye"][i]
		}
	}
	if len(bands) > 0 {
		f := treasuryFormula{ftype: "income", category: "primary", items: bracketItems(bands)}
		f.effectiveFrom, f.source = latest(bands)
		if relief != nil {
			v := relief.Rate
			f.personalRelief = &v
			f.reliefFrom = relief.EffectiveFrom
		}
		out = append(out, f)
	}
	if rows := byCat["nssf"]; len(rows) > 0 {
		f := treasuryFormula{ftype: "deduction", category: "social_security_fund", items: bracketItems(rows)}
		f.effectiveFrom, f.source = latest(rows)
		out = append(out, f)
	}
	for cat, category := range map[string]string{"shif": "shif", "housing_levy": "housing_levy"} {
		rows := byCat[cat]
		if len(rows) == 0 {
			continue
		}
		r := newest(rows)
		out = append(out, treasuryFormula{
			ftype: "deduction", category: category, effectiveFrom: r.EffectiveFrom, source: r.Source,
			items: []FormulaItemInput{{AmountFrom: decimal.Zero, AmountTo: decimal.Zero, DeductPercentage: r.Rate}},
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].category < out[j].category })
	return out
}

// bracketItems turns threshold rows into contiguous bands: each band starts where the previous
// one ended (treasury lists PAYE lower bounds as 24,001 and so on) and an absent maximum is the
// open top band (stored as 0).
func bracketItems(rows []treasury.StatutoryRate) []FormulaItemInput {
	sorted := append([]treasury.StatutoryRate(nil), rows...)
	min := func(r treasury.StatutoryRate) decimal.Decimal {
		if r.ThresholdMin == nil {
			return decimal.Zero
		}
		return *r.ThresholdMin
	}
	sort.SliceStable(sorted, func(i, j int) bool { return min(sorted[i]).LessThan(min(sorted[j])) })
	items := make([]FormulaItemInput, 0, len(sorted))
	from := decimal.Zero
	for _, r := range sorted {
		to := decimal.Zero
		if r.ThresholdMax != nil {
			to = *r.ThresholdMax
		}
		items = append(items, FormulaItemInput{AmountFrom: from, AmountTo: to, DeductPercentage: r.Rate})
		from = to
	}
	return items
}

func latest(rows []treasury.StatutoryRate) (time.Time, string) {
	r := newest(rows)
	return r.EffectiveFrom, r.Source
}

func newest(rows []treasury.StatutoryRate) treasury.StatutoryRate {
	best := rows[0]
	for _, r := range rows[1:] {
		if r.EffectiveFrom.After(best.EffectiveFrom) {
			best = r
		}
	}
	return best
}

// sameItems compares stored bands with treasury's (bounds and rates; 0 is the open bound).
func sameItems(stored []FormulaItemInput, proposed []FormulaItemInput) bool {
	if len(stored) != len(proposed) {
		return false
	}
	for i := range stored {
		a, b := stored[i], proposed[i]
		if !a.AmountFrom.Equal(b.AmountFrom) || !a.AmountTo.Equal(b.AmountTo) ||
			!a.DeductPercentage.Equal(b.DeductPercentage) || !a.DeductAmount.Equal(b.DeductAmount) {
			return false
		}
	}
	return true
}

// SyncResult reports one formula's outcome.
type SyncResult struct {
	Type, Category string
	Action         string // applied | unchanged | not_newer | no_platform_formula
	EffectiveFrom  time.Time
}

// SyncTreasuryRates applies treasury's approved, newer rate changes to the platform formulas.
func (s *Service) SyncTreasuryRates(ctx context.Context, rates []treasury.StatutoryRate) ([]SyncResult, error) {
	if s.systemTenant == uuid.Nil {
		return nil, fmt.Errorf("payroll system tenant is not configured")
	}
	var out []SyncResult
	for _, tf := range mapTreasuryRates(rates) {
		res := SyncResult{Type: tf.ftype, Category: tf.category, EffectiveFrom: tf.effectiveFrom}
		cur, err := s.orm.PayrollFormula.Query().Where(
			payrollformula.TenantID(s.systemTenant), payrollformula.TypeEQ(tf.ftype),
			payrollformula.CategoryEQ(tf.category), payrollformula.IsCurrent(true)).Only(ctx)
		if err != nil {
			res.Action = "no_platform_formula"
			out = append(out, res)
			continue
		}
		tf.effectiveFrom = tf.versionDate(cur.PersonalRelief)
		res.EffectiveFrom = tf.effectiveFrom
		if cur.EffectiveFrom != nil && !tf.effectiveFrom.After(*cur.EffectiveFrom) {
			res.Action = "not_newer"
			out = append(out, res)
			continue
		}
		stored, err := s.FormulaItems(ctx, s.systemTenant, cur.ID)
		if err != nil {
			return out, err
		}
		have := make([]FormulaItemInput, 0, len(stored))
		for _, it := range stored {
			have = append(have, FormulaItemInput{AmountFrom: it.AmountFrom, AmountTo: it.AmountTo, DeductAmount: it.DeductAmount, DeductPercentage: it.DeductPercentage})
		}
		reliefSame := tf.personalRelief == nil || tf.personalRelief.Equal(cur.PersonalRelief)
		if sameItems(have, tf.items) && reliefSame {
			res.Action = "unchanged"
			out = append(out, res)
			continue
		}
		in := FormulaInput{
			Type: tf.ftype, Category: tf.category, Title: cur.Title, Unit: cur.Unit,
			EffectiveFrom: &tf.effectiveFrom, IsCurrent: true, Progressive: cur.Progressive,
			PersonalRelief: cur.PersonalRelief, Items: tf.items,
			RegulatorySource: strings.TrimSpace("Treasury statutory rates " + tf.source),
		}
		if tf.personalRelief != nil {
			in.PersonalRelief = *tf.personalRelief
		}
		if split, _ := s.SplitRatio(ctx, s.systemTenant, cur.ID); split != nil {
			emp, empr := split.EmployeePercentage, split.EmployerPercentage
			in.EmployeePercentage, in.EmployerPercentage = &emp, &empr
		}
		if _, err := s.UpsertFormula(ctx, s.systemTenant, in); err != nil {
			return out, fmt.Errorf("%s/%s: %w", tf.ftype, tf.category, err)
		}
		res.Action = "applied"
		out = append(out, res)
	}
	return out, nil
}
