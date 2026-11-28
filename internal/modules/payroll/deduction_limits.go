package payroll

import (
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// DeferredLine is the part of a recovery the deduction limits left for a later month. The
// balance keeps it; the payslip shows it as an informational line.
type DeferredLine struct {
	Code   string // loan | advance | loss_damage | staff_purchase
	Label  string
	Amount decimal.Decimal
}

// capRecoveries puts the amounts the engine actually recovered (after the Employment Act s.19
// limits) on the itemised recovery lines and the frozen recovery allocations, and records the
// rest as deferred. The itemised lists hold one entry per recoverable with something due, in
// the engine input's order, so the n-th due recoverable of a type is the n-th entry.
func capRecoveries(in payrollengine.EmployeeInput, res payrollengine.PayslipResult, items *EmployeeItemized) {
	groups := []struct {
		code    string
		input   []payrollengine.Recoverable
		applied []decimal.Decimal
		lines   *[]LabeledAmount
	}{
		{"loan", in.Loans, res.LoansApplied, &items.Loans},
		{"advance", in.Advances, res.AdvancesApplied, &items.Advances},
		{"loss_damage", in.LossDamages, res.LossDamagesApplied, &items.LossDamages},
		{"staff_purchase", in.StaffPurchases, res.StaffPurchasesApplied, &items.StaffPurchases},
	}
	for _, g := range groups {
		lines := *g.lines
		if len(lines) == 0 {
			continue // nothing due (or advances not recovered this run)
		}
		var allocs []int
		for i, r := range items.Recoveries {
			if r.Type == g.code {
				allocs = append(allocs, i)
			}
		}
		n := 0
		for i, r := range g.input {
			want := recovered(r.Installment, r.Outstanding)
			if !want.IsPositive() {
				continue
			}
			if n >= len(lines) {
				break
			}
			got := decimal.Zero
			if i < len(g.applied) {
				got = g.applied[i]
			}
			lines[n].Amount = got
			if n < len(allocs) {
				items.Recoveries[allocs[n]].Amount = got
			}
			if short := want.Sub(got); short.IsPositive() {
				items.Deferred = append(items.Deferred, DeferredLine{Code: g.code, Label: lines[n].Label, Amount: short})
			}
			n++
		}
		kept := lines[:0]
		for _, l := range lines {
			if l.Amount.IsPositive() {
				kept = append(kept, l)
			}
		}
		*g.lines = kept
	}
}
