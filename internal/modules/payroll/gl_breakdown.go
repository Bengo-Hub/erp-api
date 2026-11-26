package payroll

import (
	"context"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/companysettings"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeloan"
	"github.com/Bengo-Hub/erp-api/internal/ent/loantype"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollcomponent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
	"github.com/Bengo-Hub/erp-api/internal/ent/recoveryline"
)

// The GL breakdown tells treasury what the run's withheld amount (gross + reimbursements - net)
// is made of, so it posts PAYE, NSSF, SHIF, Housing Levy, third-party check-offs and recoveries
// to their own payables and books the employer's statutory contributions. Treasury leaves on its
// single statutory leg whatever the breakdown does not place, and refuses a breakdown placing more
// than was withheld, so the entry always balances.

// recoveryCodes are the payslip line codes of module-driven recoveries.
var recoveryCodes = map[string]bool{"loan": true, "advance": true, "loss_damage": true, "staff_purchase": true}

// employerCodes maps employer payslip line codes to breakdown keys.
var employerCodes = map[string]string{"nssf_employer": "nssf", "housing_levy_employer": "housing_levy", "nita": "nita", "fbt": "fbt"}

// tenantCurrency is the tenant's payroll currency (company settings), KES when unset.
func (d *Disburser) tenantCurrency(ctx context.Context, tenantID uuid.UUID) string {
	cs, err := d.orm.CompanySettings.Query().Where(companysettings.TenantID(tenantID)).Only(ctx)
	if err != nil || strings.TrimSpace(cs.DefaultCurrency) == "" {
		return "KES"
	}
	return strings.ToUpper(strings.TrimSpace(cs.DefaultCurrency))
}

// buildBreakdown reads the run's payslip lines and returns the breakdown, or nil when it would
// place more than was withheld (treasury then posts the single statutory leg).
func (d *Disburser) buildBreakdown(ctx context.Context, tenantID uuid.UUID, slips []*ent.Payslip, withheld decimal.Decimal) (map[string]any, error) {
	ids := make([]uuid.UUID, len(slips))
	employee := map[string]decimal.Decimal{}
	for i, s := range slips {
		ids[i] = s.ID
		employee["paye"] = employee["paye"].Add(s.Paye)
		employee["nssf"] = employee["nssf"].Add(s.NssfEmployeeTier1).Add(s.NssfEmployeeTier2)
		employee["shif"] = employee["shif"].Add(s.ShifOrNhifContribution)
		employee["housing_levy"] = employee["housing_levy"].Add(s.HousingLevy)
	}
	lines, err := d.orm.PayslipLine.Query().Where(payslipline.TenantID(tenantID), payslipline.PayslipIDIn(ids...),
		payslipline.SectionIn(secEmployer, secAfterPaye)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("disburse: breakdown lines: %w", err)
	}
	employer := map[string]decimal.Decimal{}
	recoveries := map[string]decimal.Decimal{}
	type other struct {
		code, title string
		component   uuid.UUID
		amount      decimal.Decimal
	}
	others := map[string]*other{}
	componentIDs := map[uuid.UUID]bool{}
	for _, l := range lines {
		switch {
		case l.Section == secEmployer:
			if k, ok := employerCodes[l.Code]; ok {
				employer[k] = employer[k].Add(l.EmployerAmount)
			}
		case recoveryCodes[l.Code]:
			recoveries[l.Code] = recoveries[l.Code].Add(l.CashAmount)
		case l.ComponentID != nil:
			o, ok := others[l.ComponentID.String()]
			if !ok {
				o = &other{code: l.Code, title: l.Label, component: *l.ComponentID}
				others[l.ComponentID.String()] = o
				componentIDs[*l.ComponentID] = true
			}
			o.amount = o.amount.Add(l.CashAmount)
		}
	}

	// Account codes: a component's acc_code, a loan type's account_code.
	accCodes := map[uuid.UUID]string{}
	for _, chunk := range chunkIDs(componentIDs) {
		comps, err := d.orm.PayrollComponent.Query().Where(payrollcomponent.IDIn(chunk...)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("disburse: breakdown components: %w", err)
		}
		for _, c := range comps {
			if c.AccCode != nil {
				accCodes[c.ID] = strings.TrimSpace(*c.AccCode)
			}
		}
	}
	loanByCode, err := d.loanRecoveriesByAccount(ctx, tenantID, ids)
	if err != nil {
		return nil, err
	}

	placed := decimal.Zero
	empOut := map[string]any{}
	for k, v := range employee {
		if v.IsPositive() {
			empOut[k] = v.StringFixed(2)
			placed = placed.Add(v)
		}
	}
	erOut := map[string]any{}
	for k, v := range employer {
		if v.IsPositive() {
			erOut[k] = v.StringFixed(2)
		}
	}
	recOut := []map[string]any{}
	loanPlaced := decimal.Zero
	for code, amt := range loanByCode {
		recOut = append(recOut, map[string]any{"type": "loan", "account_code": code, "amount": amt.StringFixed(2)})
		loanPlaced = loanPlaced.Add(amt)
		placed = placed.Add(amt)
	}
	for typ, amt := range recoveries {
		if typ == "loan" {
			amt = amt.Sub(loanPlaced) // the part without a loan type account code
		}
		if amt.IsPositive() {
			recOut = append(recOut, map[string]any{"type": typ, "amount": amt.StringFixed(2)})
		}
	}
	otherOut := []map[string]any{}
	for _, o := range others {
		if !o.amount.IsPositive() {
			continue
		}
		e := map[string]any{"code": o.code, "title": o.title, "amount": o.amount.StringFixed(2)}
		if c := accCodes[o.component]; c != "" {
			e["account_code"] = c
		}
		otherOut = append(otherOut, e)
		placed = placed.Add(o.amount)
	}
	if placed.GreaterThan(withheld) {
		if d.log != nil {
			d.log.Warn("payroll breakdown places more than was withheld; sending the totals only")
		}
		return nil, nil
	}
	return map[string]any{"employee": empOut, "employer": erOut, "recoveries": recOut, "other_deductions": otherOut}, nil
}

// loanRecoveriesByAccount sums the run's loan recoveries per loan type account code (only loan
// types that carry one).
func (d *Disburser) loanRecoveriesByAccount(ctx context.Context, tenantID uuid.UUID, slipIDs []uuid.UUID) (map[string]decimal.Decimal, error) {
	out := map[string]decimal.Decimal{}
	recs, err := d.orm.RecoveryLine.Query().Where(recoveryline.TenantID(tenantID), recoveryline.PayslipIDIn(slipIDs...),
		recoveryline.RecoverableTypeEQ(recoveryline.RecoverableTypeLoan)).All(ctx)
	if err != nil || len(recs) == 0 {
		return out, err
	}
	loanIDs := map[uuid.UUID]bool{}
	for _, r := range recs {
		loanIDs[r.RecoverableID] = true
	}
	typeOf := map[uuid.UUID]uuid.UUID{}
	typeIDs := map[uuid.UUID]bool{}
	for _, chunk := range chunkIDs(loanIDs) {
		loans, err := d.orm.EmployeeLoan.Query().Where(employeeloan.TenantID(tenantID), employeeloan.IDIn(chunk...), employeeloan.LoanTypeIDNotNil()).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, l := range loans {
			typeOf[l.ID] = *l.LoanTypeID
			typeIDs[*l.LoanTypeID] = true
		}
	}
	codeOf := map[uuid.UUID]string{}
	for _, chunk := range chunkIDs(typeIDs) {
		types, err := d.orm.LoanType.Query().Where(loantype.IDIn(chunk...), loantype.AccountCodeNotNil()).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, t := range types {
			if c := strings.TrimSpace(*t.AccountCode); c != "" {
				codeOf[t.ID] = c
			}
		}
	}
	for _, r := range recs {
		if c := codeOf[typeOf[r.RecoverableID]]; c != "" {
			out[c] = out[c].Add(r.Amount)
		}
	}
	return out, nil
}
