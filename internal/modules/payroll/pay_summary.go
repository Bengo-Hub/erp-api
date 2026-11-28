package payroll

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// Pay summary states.
const (
	PaySummaryOK         = "ok"
	PaySummaryNoSalary   = "no_salary"    // no active salary: there is nothing to compute
	PaySummaryNotOnRun   = "not_on_run"   // casual, consultant, exited or no contract for the month
	PaySummaryUncomputed = "not_computed" // the preview failed; Reason says why
)

// How a summary line comes about.
const (
	OriginStatutory = "statutory" // by law, following the organisation's statutory switches
	OriginAutomatic = "automatic" // salary, loans, advances, attendance and other modules' records
	OriginAssigned  = "assigned"  // given to this employee
)

// PaySummaryLine is one thing payroll applies to the employee for the month.
type PaySummaryLine struct {
	Code     string           `json:"code"`
	Label    string           `json:"label"`
	Kind     string           `json:"kind"` // earning | benefit | deduction | relief | employer | reimbursement | not_deducted
	Origin   string           `json:"origin"`
	Employee *decimal.Decimal `json:"employee_amount,omitempty"`
	Employer *decimal.Decimal `json:"employer_amount,omitempty"`
	// Off is set on a statutory item the organisation has switched off.
	Off bool `json:"off,omitempty"`
}

// PaySummary is what a payroll run would apply to one employee for a month.
type PaySummary struct {
	Period string           `json:"period"`
	State  string           `json:"state"`
	Reason string           `json:"reason,omitempty"`
	Lines  []PaySummaryLine `json:"lines"`
	Gross  *decimal.Decimal `json:"gross_pay,omitempty"`
	Net    *decimal.Decimal `json:"net_pay,omitempty"`
	// Notes are the person's own tax position (second job, exemption certificate).
	Notes []string `json:"notes,omitempty"`
}

// statutoryLines maps a statutory component code to its payslip line codes.
var statutoryLines = map[string][]string{
	"paye": {"paye"}, "nssf": {"nssf_t1", "nssf_t2", "nssf_employer"}, "shif": {"shif"},
	"housing_levy": {"housing_levy", "housing_levy_employer"}, "nita": {"nita"},
}

var statutoryLineCodes = func() map[string]bool {
	m := map[string]bool{"personal_relief": true, "insurance_relief": true}
	for _, codes := range statutoryLines {
		for _, c := range codes {
			m[c] = true
		}
	}
	return m
}()

// automaticLineCodes are lines other modules produce.
var automaticLineCodes = map[string]bool{"basic": true, "loan": true, "advance": true, "loss_damage": true,
	"staff_purchase": true, "attendance_deduction": true, "overtime": true, "holiday_pay": true, "piece_work": true, claimEarningCode: true}

// EmployeePaySummary previews the month for one employee through the same run a payroll uses and
// lists its lines, with the statutory items the organisation switched off named as off. Without
// an active salary it says so and lists the statutory items without amounts.
func (s *Service) EmployeePaySummary(ctx context.Context, tenantID, employeeID uuid.UUID, period time.Time) (*PaySummary, error) {
	if ok, err := s.orm.Employee.Query().Where(employee.ID(employeeID), employee.TenantID(tenantID), employee.Deleted(false)).Exist(ctx); err != nil {
		return nil, err
	} else if !ok {
		return nil, &ent.NotFoundError{}
	}
	out := &PaySummary{Period: period.Format("2006-01"), State: PaySummaryOK, Lines: []PaySummaryLine{}}
	statutory, err := s.settings.ResolveComponents(ctx, tenantID, payrollsettings.CategoryDeductions)
	if err != nil {
		return nil, err
	}
	// The salary in force for the month shown (a scheduled raise from its month on).
	rows, err := s.orm.SalaryDetails.Query().
		Where(salarydetails.TenantID(tenantID), salarydetails.EmployeeID(employeeID), salarydetails.IsActive(true)).
		Order(ent.Desc(salarydetails.FieldCreatedAt)).All(ctx)
	sd := employees.SalaryInForce(rows, employees.MonthEnd(period))
	if err == nil && sd == nil {
		err = &ent.NotFoundError{}
	}
	if ent.IsNotFound(err) || (err == nil && !sd.MonthlySalary.IsPositive()) {
		out.State, out.Reason = PaySummaryNoSalary, "No salary is set for this employee, so nothing can be computed yet."
		out.addStatutory(statutory, nil)
		return out, nil
	}
	if err != nil {
		return nil, err
	}
	switch {
	case sd.IncomeTax == "secondary":
		out.Notes = append(out.Notes, "Secondary employment: taxed at the top rate with no personal relief.")
	case sd.IncomeTax == "none":
		out.Notes = append(out.Notes, "Tax exempt: no PAYE is charged.")
	}
	if sd.DisabilityExempt {
		out.Notes = append(out.Notes, "Holds a disability exemption certificate.")
	}

	res, err := s.Run(ctx, RunParams{TenantID: tenantID, Period: period, EmployeeIDs: []uuid.UUID{employeeID}, RecoverAdvances: true})
	if err != nil {
		out.State, out.Reason = PaySummaryUncomputed, strings.TrimPrefix(err.Error(), fmt.Sprintf("payroll: employee %s: ", employeeID))
		out.addStatutory(statutory, nil)
		return out, nil
	}
	if len(res) == 0 {
		out.State, out.Reason = PaySummaryNotOnRun, "This employee is not on this month's payroll run (casual, consultant, exited, or no contract covers the month)."
		out.addStatutory(statutory, nil)
		return out, nil
	}
	lines, r := res[0].Lines, res[0].Result
	gross, net := r.GrossPay, r.NetPay
	out.Gross, out.Net = &gross, &net

	seen := map[string]bool{}
	for _, l := range lines {
		seen[l.Code] = true
		out.Lines = append(out.Lines, summaryLine(l))
	}
	// Pre-tax reliefs lower chargeable pay and have no payslip line of their own.
	for _, x := range []struct {
		code, label string
		amount      decimal.Decimal
	}{{"pension_relief", "Pension Relief", r.PensionDeduction}, {"mortgage_relief", "Mortgage Interest Relief", r.MortgageDeduction},
		{"disability_relief", "Disability Exemption", r.DisabilityExemption}} {
		if x.amount.IsPositive() {
			v := x.amount
			out.Lines = append(out.Lines, PaySummaryLine{Code: x.code, Label: x.label, Kind: "relief", Origin: OriginStatutory, Employee: &v})
		}
	}
	out.attachEmployerShares(r.NSSFEmployeeTier1, r.NSSFEmployeeTier2, r.NSSFEmployer, r.HousingLevyEmployer)
	out.addStatutory(statutory, seen)
	return out, nil
}

// attachEmployerShares shows a shared deduction's employer part on the employee's own row, so
// the Employee and Employer columns read across one line: NSSF, matched per tier (NSSF Act 2013),
// and the Housing Levy, matched 1.5% (Affordable Housing Act s.4). The separate employer row the
// share came from is then dropped. Employer-only items (NITA) keep their own row, and a share whose
// employee row is missing (the deduction was not charged) keeps its separate row too.
func (o *PaySummary) attachEmployerShares(t1, t2, nssfEmployer, ahlEmployer decimal.Decimal) {
	idx := map[string]int{}
	for i, l := range o.Lines {
		idx[l.Code] = i
	}
	drop := map[string]bool{}
	set := func(code string, v decimal.Decimal) {
		if i, ok := idx[code]; ok {
			o.Lines[i].Employer = &v
		}
	}
	_, hasT1 := idx["nssf_t1"]
	_, hasT2 := idx["nssf_t2"]
	if nssfEmployer.IsPositive() && (hasT1 || hasT2) {
		// The employer total split across the tiers in the employee's proportion; under the
		// matched rule this is exactly each tier's employee amount.
		employee := t1.Add(t2)
		er1 := nssfEmployer
		if employee.IsPositive() && hasT2 {
			er1 = nssfEmployer.Mul(t1).Div(employee).Round(2)
		}
		if hasT1 {
			set("nssf_t1", er1)
		}
		if hasT2 {
			set("nssf_t2", nssfEmployer.Sub(er1))
			if !hasT1 {
				set("nssf_t2", nssfEmployer)
			}
		}
		drop["nssf_employer"] = true
	}
	if ahlEmployer.IsPositive() {
		if _, ok := idx["housing_levy"]; ok {
			set("housing_levy", ahlEmployer)
			drop["housing_levy_employer"] = true
		} else {
			v := ahlEmployer
			o.Lines = append(o.Lines, PaySummaryLine{Code: "housing_levy_employer", Label: "Housing Levy Employer",
				Kind: "employer", Origin: OriginStatutory, Employer: &v})
		}
	}
	if len(drop) == 0 {
		return
	}
	kept := o.Lines[:0]
	for _, l := range o.Lines {
		if !drop[l.Code] {
			kept = append(kept, l)
		}
	}
	o.Lines = kept
}

// addStatutory lists the statutory components that have no line in seen: switched off ones as
// off, and the rest (no charge this month, or nothing computed) without an amount.
func (o *PaySummary) addStatutory(comps []payrollsettings.ResolvedComponent, seen map[string]bool) {
	for _, c := range comps {
		codes, ok := statutoryLines[c.Code]
		if !ok || !c.Statutory {
			continue
		}
		listed := false
		for _, code := range codes {
			listed = listed || seen[code]
		}
		if listed {
			continue
		}
		kind := "deduction"
		if c.Code == "nita" {
			kind = "employer"
		}
		l := PaySummaryLine{Code: c.Code, Label: c.Title, Kind: kind, Origin: OriginStatutory, Off: !c.Active}
		if c.Active && seen != nil {
			zero := decimal.Zero // computed, and nothing is due
			l.Employee = &zero
		}
		o.Lines = append(o.Lines, l)
	}
}

func summaryLine(l ComposedLine) PaySummaryLine {
	out := PaySummaryLine{Code: l.Code, Label: l.Label, Origin: OriginAssigned}
	switch {
	case statutoryLineCodes[l.Code]:
		out.Origin = OriginStatutory
	case automaticLineCodes[l.Code]:
		out.Origin = OriginAutomatic
	}
	cash, employer := l.Cash, l.Employer
	switch l.Section {
	case secEarningCash:
		out.Kind, out.Employee = "earning", &cash
	case secBenefitNonCash:
		out.Kind, out.Employee = "benefit", &cash
	case secRelief:
		out.Kind, out.Employee = "relief", &cash
	case secReimbursement:
		out.Kind, out.Employee = "reimbursement", &cash
	case secEmployer:
		out.Kind, out.Employer = "employer", &employer
	case secShortfall:
		out.Kind, out.Employee = "not_deducted", &cash
	default:
		out.Kind, out.Employee = "deduction", &cash
	}
	return out
}
