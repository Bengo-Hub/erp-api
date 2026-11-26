package payrollsettings

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
)

// datedRule is one platform rule kept as a formula version: values in the metadata (or bands),
// in force between its dates. A non-current row without dates never applies.
type datedRule struct {
	ftype, category, title, source, notes string
	from, to                              *time.Time
	current                               bool
	meta                                  map[string]any
	bands                                 []FormulaItemInput
	personalRelief                        decimal.Decimal
}

func ruleDate(y int, m time.Month, d int) *time.Time {
	t := time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
	return &t
}

// pctItem is one PAYE band; an upper bound of 0 means open ended.
func pctItem(from, to int64, pct string) FormulaItemInput {
	return FormulaItemInput{AmountFrom: decimal.NewFromInt(from), AmountTo: decimal.NewFromInt(to), DeductPercentage: decimal.RequireFromString(pct)}
}

// datedRules are the platform's dated rules, each confirmed from the primary text named in its
// source. KRA publishes a new market interest rate every quarter: add the next quarter's row (and
// close the current one) when the notice is out.
var datedRules = []datedRule{
	{
		ftype: FormulaTypeReliefAllowance, category: FormulaCategoryPerDiem,
		title:  "Per diem tax-free limit",
		source: "Income Tax Act (Cap. 470) s.5(2)(a)(iii), as amended by Finance Act 2025 s.3 (in force 1 July 2025)",
		notes:  "The first 10,000 shillings per day away from the usual place of work on official duty is excluded from gains.",
		from:   ruleDate(2025, 7, 1), current: true,
		meta: map[string]any{MetaDailyExempt: "10000"},
	},
	{
		ftype: FormulaTypeFBT, category: FormulaCategoryFBT,
		title:  "Fringe benefit tax, July to September 2026",
		source: "Income Tax Act s.12B and Third Schedule para 15; KRA public notice of 14 July 2026",
		from:   ruleDate(2026, 7, 1), to: ruleDate(2026, 9, 30),
		meta: map[string]any{MetaFBTTaxRate: "0.30", MetaMarketInterestRate: "8"},
	},
	{
		ftype: FormulaTypeFBT, category: FormulaCategoryFBT,
		title:  "Fringe benefit tax, October to December 2026",
		source: "Income Tax Act s.12B and Third Schedule para 15; KRA public notice of 22 October 2026",
		notes:  "Stays in force until the next quarter's rate is added.",
		from:   ruleDate(2026, 10, 1), current: true,
		meta: map[string]any{MetaFBTTaxRate: "0.30", MetaMarketInterestRate: "9"},
	},
	{
		ftype: "income", category: "primary",
		title:  "P.A.Y.E. (Tax Laws (Amendment) Bill 2026, proposed)",
		source: "Tax Laws (Amendment) Bill 2026 (not enacted)",
		notes: "Inactive: not law. Announced: 0% up to 30,000 and 25% on the next 20,000. The bands above " +
			"50,000 repeat the Finance Act 2023 bands until the bill text is published. Give it a start date " +
			"and make it current only once the Act is in force.",
		personalRelief: decimal.NewFromInt(2400),
		bands: []FormulaItemInput{
			pctItem(0, 30000, "0"), pctItem(30000, 50000, "25"), pctItem(50000, 500000, "30"),
			pctItem(500000, 800000, "32.5"), pctItem(800000, 0, "35"),
		},
	},
}

// EnsureDatedRules adds the dated rules missing on the platform (matched by type, category and
// title). Existing rows are never changed, so platform edits survive redeploys. Returns how many
// rows it created.
func EnsureDatedRules(ctx context.Context, orm *ent.Client, systemTenant uuid.UUID) (int, error) {
	created := 0
	for _, r := range datedRules {
		exists, err := orm.PayrollFormula.Query().Where(payrollformula.TenantID(systemTenant),
			payrollformula.TypeEQ(r.ftype), payrollformula.CategoryEQ(r.category), payrollformula.Title(r.title)).Exist(ctx)
		if err != nil {
			return created, err
		}
		if exists {
			continue
		}
		tx, err := orm.Tx(ctx)
		if err != nil {
			return created, err
		}
		c := tx.PayrollFormula.Create().SetTenantID(systemTenant).SetType(r.ftype).SetCategory(r.category).
			SetTitle(r.title).SetRegulatorySource(r.source).SetIsCurrent(r.current).
			SetProgressive(r.ftype == "income").SetPersonalRelief(r.personalRelief).SetVersion("1.0").
			SetNillableEffectiveFrom(r.from).SetNillableEffectiveTo(r.to)
		if r.notes != "" {
			c = c.SetNotes(r.notes)
		}
		if r.meta != nil {
			c = c.SetMetadata(r.meta)
		}
		f, err := c.Save(ctx)
		if err == nil {
			for _, b := range r.bands {
				if _, err = tx.PayrollFormulaItem.Create().SetTenantID(systemTenant).SetFormulaID(f.ID).
					SetAmountFrom(b.AmountFrom).SetAmountTo(b.AmountTo).SetDeductAmount(b.DeductAmount).
					SetDeductPercentage(b.DeductPercentage).Save(ctx); err != nil {
					break
				}
			}
		}
		if err != nil {
			_ = tx.Rollback()
			return created, err
		}
		if err := tx.Commit(); err != nil {
			return created, err
		}
		created++
	}
	return created, nil
}
