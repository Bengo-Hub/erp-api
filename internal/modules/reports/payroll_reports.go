package reports

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
)

// KRA pension-deduction ceiling constants: deductible pension = min(E1 30%×gross, E2 actual, E3 cap).
var (
	pensionPct30 = decimal.NewFromFloat(0.30)
	pensionCap30 = decimal.NewFromInt(30000)
)

// Report is the common envelope every report returns: a typed name, the period, column
// headers (for generic table rendering/export), rows, and a totals map.
type Report struct {
	Report  string           `json:"report"`
	Period  PeriodMeta       `json:"period"`
	Columns []string         `json:"columns"`
	Rows    []map[string]any `json:"rows"`
	Totals  map[string]any   `json:"totals"`
	// ColumnDefs (optional) drives a backend-defined dynamic table: header label + type per key.
	// When present the frontend renders these columns (with horizontal scroll + Edit-Columns)
	// instead of its static config; empty = the report uses the static config columns.
	ColumnDefs []ColumnDef `json:"column_defs,omitempty"`
	// Sheets (optional) drives a MULTI-SHEET export (one worksheet per entry) for KRA statutory
	// returns that span several schedules (P9A 12-month grid, P10 Sheet B1/B2/M, NSSF SF24). When
	// present, xlsx renders one sheet per entry; Columns/Rows above remain the flat CSV/JSON view.
	Sheets []ReportSheet `json:"sheets,omitempty"`
}

// ReportSheet is one worksheet of a multi-sheet statutory workbook.
type ReportSheet struct {
	Name    string           `json:"name"`
	Columns []string         `json:"columns"`
	Rows    []map[string]any `json:"rows"`
	Totals  map[string]any   `json:"totals,omitempty"`
}

// ColumnDef describes one backend-driven report column.
type ColumnDef struct {
	Key     string `json:"key"`
	Header  string `json:"header"`
	Money   bool   `json:"money,omitempty"`
	Numeric bool   `json:"numeric,omitempty"`
	Sticky  bool   `json:"sticky,omitempty"` // pin to the left (staff no / name)
}

// PeriodMeta echoes the resolved window back to the caller.
type PeriodMeta struct {
	Start string `json:"start"`
	End   string `json:"end"`
}

func periodMeta(f Filter) PeriodMeta {
	return PeriodMeta{Start: f.Start.Format("2006-01-02"), End: f.End.Format("2006-01-02")}
}

func money(d decimal.Decimal) string { return d.StringFixed(2) }

// p9Acc accumulates a single employee's figures across the period's payslips (a true P9 is the
// per-employee annual card, so multiple monthly payslips collapse into one row).
type p9Acc struct {
	e                                       *ent.Employee
	gross, taxable, relief, paye, nssf, net decimal.Decimal
	shif, ahl                               decimal.Decimal
	insurance, pension, mortgage, disabled  decimal.Decimal
}

// P9 is the KRA Tax Deduction Card: ONE row per employee with year-to-date gross, deductions,
// chargeable (taxable) pay and PAYE. Column keys match the erp-ui report-runner contract.
func (s *Service) P9(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	byEmp := map[uuid.UUID]*p9Acc{}
	order := []uuid.UUID{}
	for _, p := range slips {
		a := byEmp[p.EmployeeID]
		if a == nil {
			a = &p9Acc{e: emps[p.EmployeeID]}
			byEmp[p.EmployeeID] = a
			order = append(order, p.EmployeeID)
		}
		a.gross = a.gross.Add(p.GrossPay)
		a.taxable = a.taxable.Add(p.TaxablePay)
		a.relief = a.relief.Add(p.TaxRelief)
		a.paye = a.paye.Add(p.Paye)
		a.nssf = a.nssf.Add(p.NssfEmployeeTier1).Add(p.NssfEmployeeTier2)
		a.shif = a.shif.Add(p.ShifOrNhifContribution)
		a.ahl = a.ahl.Add(p.HousingLevy)
		a.insurance = a.insurance.Add(p.InsuranceRelief)
		a.pension = a.pension.Add(p.PensionDeduction)
		a.mortgage = a.mortgage.Add(p.MortgageDeduction)
		a.disabled = a.disabled.Add(p.DisabilityExemption)
		a.net = a.net.Add(p.NetPay)
	}
	// P9 (KRA Tax Deduction Card) columns — includes the allowable pre-tax deductions
	// (NSSF, SHIF, AHL) and the personal-relief credit so the card reconciles to PAYE.
	rep := &Report{
		Report:  "P9",
		Period:  periodMeta(f),
		Columns: []string{"employee_name", "employee_pin", "national_id", "total_gross_pay", "nssf", "pension_deduction", "shif", "housing_levy", "mortgage_relief", "disability_exemption", "total_deductions", "chargeable_pay", "tax_charged", "personal_relief", "insurance_relief", "total_tax", "net_pay"},
		Rows:    []map[string]any{},
	}
	totChargeable, totPaye, totNet := d(), d(), d()
	for _, id := range order {
		a := byEmp[id]
		deductions := a.gross.Sub(a.net)
		// tax charged = PAYE before the relief credits (PAYE = tax_charged − relief).
		taxCharged := a.paye.Add(a.relief)
		// a.relief (tax_relief) = personal + insurance; show the personal portion separately.
		personal := a.relief.Sub(a.insurance)
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name":        empName(a.e),
			"employee_pin":         pin(a.e),
			"national_id":          natID(a.e),
			"total_gross_pay":      money(a.gross),
			"nssf":                 money(a.nssf),
			"pension_deduction":    money(a.pension),
			"shif":                 money(a.shif),
			"housing_levy":         money(a.ahl),
			"mortgage_relief":      money(a.mortgage),
			"disability_exemption": money(a.disabled),
			"total_deductions":     money(deductions),
			"chargeable_pay":       money(a.taxable),
			"tax_charged":          money(taxCharged),
			"personal_relief":      money(personal),
			"insurance_relief":     money(a.insurance),
			"total_tax":            money(a.paye),
			"net_pay":              money(a.net),
		})
		totChargeable = totChargeable.Add(a.taxable)
		totPaye = totPaye.Add(a.paye)
		totNet = totNet.Add(a.net)
	}
	rep.Totals = map[string]any{
		"count": len(order), "chargeable_pay": money(totChargeable),
		"total_tax": money(totPaye), "net_pay": money(totNet),
	}
	return rep, nil
}

// p9aCols are the monthly-grid columns of the KRA P9A card, including the pension E1/E2/E3
// ceiling breakout (E1 = 30% of gross, E2 = actual scheme contribution, E3 = 30,000 cap) and the
// resulting deductible pension = min(E1, E2, E3).
var p9aCols = []string{
	"month", "gross_pay", "nssf", "pension_e1_30pct", "pension_e2_actual", "pension_e3_cap",
	"deductible_pension", "shif", "housing_levy", "mortgage_relief", "chargeable_pay",
	"tax_charged", "personal_relief", "insurance_relief", "disability_exemption", "paye", "net_pay",
}

// P9A is the KRA employee Tax Deduction Card as a MULTI-SHEET workbook: one worksheet per employee
// with a Jan–Dec monthly grid (the true iTax P9A layout, including the pension deductible and the
// insurance/mortgage/disability reliefs). The flat Columns/Rows carry an annual per-employee
// summary for CSV/JSON consumers.
func (s *Service) P9A(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	// Actual monthly scheme contribution (E2) per employee, from salary_details.
	salPension := map[uuid.UUID]decimal.Decimal{}
	if sals, serr := s.orm.SalaryDetails.Query().
		Where(salarydetails.TenantID(tenantID), salarydetails.IsActive(true)).All(ctx); serr == nil {
		for _, sd := range sals {
			salPension[sd.EmployeeID] = sd.PensionContribution
		}
	}
	byEmp := map[uuid.UUID][]*ent.Payslip{}
	order := []uuid.UUID{}
	for _, p := range slips {
		if _, ok := byEmp[p.EmployeeID]; !ok {
			order = append(order, p.EmployeeID)
		}
		byEmp[p.EmployeeID] = append(byEmp[p.EmployeeID], p)
	}

	rep := &Report{
		Report:  "P9A",
		Period:  periodMeta(f),
		Columns: []string{"employee_name", "employee_pin", "national_id", "total_gross_pay", "total_chargeable", "total_paye", "total_net"},
		Rows:    []map[string]any{},
	}
	for idx, id := range order {
		list := byEmp[id]
		sort.SliceStable(list, func(i, j int) bool { return periodTimeOf(list[i]).Before(periodTimeOf(list[j])) })
		e := emps[id]
		sheet := ReportSheet{Name: p9aSheetName(e, idx), Columns: p9aCols, Rows: []map[string]any{}}
		tg, tc, tp, tn := d(), d(), d(), d()
		for _, p := range list {
			personal := p.TaxRelief.Sub(p.InsuranceRelief) // tax_relief = personal + insurance
			sheet.Rows = append(sheet.Rows, map[string]any{
				"month":                monthLabel(p),
				"gross_pay":            money(p.GrossPay),
				"nssf":                 money(p.NssfEmployeeTier1.Add(p.NssfEmployeeTier2)),
				"pension_e1_30pct":     money(p.GrossPay.Mul(pensionPct30)),
				"pension_e2_actual":    money(salPension[p.EmployeeID]),
				"pension_e3_cap":       money(pensionCap30),
				"deductible_pension":   money(p.PensionDeduction),
				"shif":                 money(p.ShifOrNhifContribution),
				"housing_levy":         money(p.HousingLevy),
				"mortgage_relief":      money(p.MortgageDeduction),
				"chargeable_pay":       money(p.TaxablePay),
				"tax_charged":          money(p.Paye.Add(p.TaxRelief)),
				"personal_relief":      money(personal),
				"insurance_relief":     money(p.InsuranceRelief),
				"disability_exemption": money(p.DisabilityExemption),
				"paye":                 money(p.Paye),
				"net_pay":              money(p.NetPay),
			})
			tg, tc, tp, tn = tg.Add(p.GrossPay), tc.Add(p.TaxablePay), tp.Add(p.Paye), tn.Add(p.NetPay)
		}
		sheet.Totals = map[string]any{"month": "TOTAL", "gross_pay": money(tg), "chargeable_pay": money(tc), "paye": money(tp), "net_pay": money(tn)}
		rep.Sheets = append(rep.Sheets, sheet)
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name": empName(e), "employee_pin": pin(e), "national_id": natID(e),
			"total_gross_pay": money(tg), "total_chargeable": money(tc), "total_paye": money(tp), "total_net": money(tn),
		})
	}
	return rep, nil
}

// p9aSheetName builds a unique, xlsx-safe worksheet name (≤31 chars, no []:*?/\) for an employee.
func p9aSheetName(e *ent.Employee, idx int) string {
	name := empName(e)
	if name == "" {
		name = "Employee"
	}
	name = strings.NewReplacer("[", "(", "]", ")", ":", "-", "*", "-", "?", "-", "/", "-", "\\", "-").Replace(name)
	prefix := fmt.Sprintf("%d ", idx+1) // guarantees uniqueness even for duplicate names
	if len(name) > 31-len(prefix) {
		name = name[:31-len(prefix)]
	}
	return prefix + name
}

func monthLabel(p *ent.Payslip) string {
	if p.PaymentPeriod != nil {
		return p.PaymentPeriod.Format("Jan 2006")
	}
	return ""
}

func periodTimeOf(p *ent.Payslip) time.Time {
	if p.PaymentPeriod != nil {
		return *p.PaymentPeriod
	}
	return time.Time{}
}

// p10aAcc accumulates an employer-return row per employee across the period.
type p10aAcc struct {
	e                            *ent.Employee
	gross, paye, nssf, shif, ahl decimal.Decimal
}

// P10A is the employer PAYE return: ONE row per employee with year-to-date gross, PAYE, NSSF and
// SHIF/NHIF. Column keys match the erp-ui report-runner contract (total_gross_pay/total_paye/…).
func (s *Service) P10A(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	byEmp := map[uuid.UUID]*p10aAcc{}
	order := []uuid.UUID{}
	for _, p := range slips {
		a := byEmp[p.EmployeeID]
		if a == nil {
			a = &p10aAcc{e: emps[p.EmployeeID]}
			byEmp[p.EmployeeID] = a
			order = append(order, p.EmployeeID)
		}
		a.gross = a.gross.Add(p.GrossPay)
		a.paye = a.paye.Add(p.Paye)
		a.nssf = a.nssf.Add(p.NssfEmployeeTier1).Add(p.NssfEmployeeTier2)
		a.shif = a.shif.Add(p.ShifOrNhifContribution)
		a.ahl = a.ahl.Add(p.HousingLevy)
	}
	rep := &Report{
		Report:  "P10A",
		Period:  periodMeta(f),
		Columns: []string{"employee_name", "employee_pin", "total_gross_pay", "total_paye", "total_nssf", "total_shif", "total_housing_levy"},
		Rows:    []map[string]any{},
	}
	totGross, totPaye := d(), d()
	for _, id := range order {
		a := byEmp[id]
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name":      empName(a.e),
			"employee_pin":       pin(a.e),
			"total_gross_pay":    money(a.gross),
			"total_paye":         money(a.paye),
			"total_nssf":         money(a.nssf),
			"total_shif":         money(a.shif),
			"total_housing_levy": money(a.ahl),
		})
		totGross = totGross.Add(a.gross)
		totPaye = totPaye.Add(a.paye)
	}
	rep.Totals = map[string]any{"count": len(order), "total_gross_pay": money(totGross), "total_paye": money(totPaye)}
	return rep, nil
}

// P10 is the employer annual PAYE return as the MULTI-SHEET iTax workbook:
//   - Sheet B1: employees liable to PAYE (paye > 0)
//   - Sheet B2: employees not liable (below the threshold)
//   - Sheet M:  Affordable Housing Levy per employee (employee 1.5% + employer 1.5%)
// The flat Columns/Rows carry a per-employee summary for CSV/JSON.
func (s *Service) P10(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	type acc struct {
		e                              *ent.Employee
		gross, taxable, nssf, shif, ahl, paye decimal.Decimal
	}
	byEmp := map[uuid.UUID]*acc{}
	order := []uuid.UUID{}
	for _, p := range slips {
		a := byEmp[p.EmployeeID]
		if a == nil {
			a = &acc{e: emps[p.EmployeeID]}
			byEmp[p.EmployeeID] = a
			order = append(order, p.EmployeeID)
		}
		a.gross = a.gross.Add(p.GrossPay)
		a.taxable = a.taxable.Add(p.TaxablePay)
		a.nssf = a.nssf.Add(p.NssfEmployeeTier1).Add(p.NssfEmployeeTier2)
		a.shif = a.shif.Add(p.ShifOrNhifContribution)
		a.ahl = a.ahl.Add(p.HousingLevy)
		a.paye = a.paye.Add(p.Paye)
	}
	b1 := ReportSheet{Name: "B1 - PAYE", Columns: []string{"employee_name", "employee_pin", "gross_pay", "nssf", "shif", "chargeable_pay", "paye"}, Rows: []map[string]any{}}
	b2 := ReportSheet{Name: "B2 - Below Threshold", Columns: []string{"employee_name", "employee_pin", "gross_pay", "reason"}, Rows: []map[string]any{}}
	m := ReportSheet{Name: "Sheet M - AHL", Columns: []string{"employee_name", "employee_pin", "gross_pay", "employee_ahl", "employer_ahl", "total_ahl"}, Rows: []map[string]any{}}
	rep := &Report{
		Report:  "P10",
		Period:  periodMeta(f),
		Columns: []string{"employee_name", "employee_pin", "gross_pay", "chargeable_pay", "paye", "paye_liable"},
		Rows:    []map[string]any{},
	}
	totGross, totPaye, totAHL := d(), d(), d()
	for _, id := range order {
		a := byEmp[id]
		if a.paye.IsPositive() {
			b1.Rows = append(b1.Rows, map[string]any{
				"employee_name": empName(a.e), "employee_pin": pin(a.e), "gross_pay": money(a.gross),
				"nssf": money(a.nssf), "shif": money(a.shif), "chargeable_pay": money(a.taxable), "paye": money(a.paye),
			})
		} else {
			b2.Rows = append(b2.Rows, map[string]any{
				"employee_name": empName(a.e), "employee_pin": pin(a.e), "gross_pay": money(a.gross), "reason": "Below PAYE threshold",
			})
		}
		m.Rows = append(m.Rows, map[string]any{
			"employee_name": empName(a.e), "employee_pin": pin(a.e), "gross_pay": money(a.gross),
			"employee_ahl": money(a.ahl), "employer_ahl": money(a.ahl), "total_ahl": money(a.ahl.Add(a.ahl)),
		})
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name": empName(a.e), "employee_pin": pin(a.e), "gross_pay": money(a.gross),
			"chargeable_pay": money(a.taxable), "paye": money(a.paye), "paye_liable": a.paye.IsPositive(),
		})
		totGross, totPaye, totAHL = totGross.Add(a.gross), totPaye.Add(a.paye), totAHL.Add(a.ahl)
	}
	b1.Totals = map[string]any{"employee_name": "TOTAL", "gross_pay": money(totGross), "paye": money(totPaye)}
	m.Totals = map[string]any{"employee_name": "TOTAL", "employee_ahl": money(totAHL), "employer_ahl": money(totAHL), "total_ahl": money(totAHL.Add(totAHL))}
	rep.Sheets = []ReportSheet{b1, b2, m}
	rep.Totals = map[string]any{"count": len(order), "gross_pay": money(totGross), "paye": money(totPaye)}
	return rep, nil
}

// Statutory is the combined statutory-deductions schedule (PAYE + SHIF/NHIF + NSSF + housing).
func (s *Service) Statutory(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	rep := &Report{
		Report:  "statutory",
		Period:  periodMeta(f),
		Columns: []string{"employee", "paye", "shif_nhif", "nssf_employee", "nssf_employer", "housing_levy"},
		Rows:    []map[string]any{},
	}
	totPaye, totShif, totNssfE, totNssfR, totHouse := d(), d(), d(), d(), d()
	for _, p := range slips {
		nssfE := p.NssfEmployeeTier1.Add(p.NssfEmployeeTier2)
		rep.Rows = append(rep.Rows, map[string]any{
			"employee":      empName(emps[p.EmployeeID]),
			"paye":          money(p.Paye),
			"shif_nhif":     money(p.ShifOrNhifContribution),
			"nssf_employee": money(nssfE),
			"nssf_employer": money(p.NssfEmployerContribution),
			"housing_levy":  money(p.HousingLevy),
		})
		totPaye = totPaye.Add(p.Paye)
		totShif = totShif.Add(p.ShifOrNhifContribution)
		totNssfE = totNssfE.Add(nssfE)
		totNssfR = totNssfR.Add(p.NssfEmployerContribution)
		totHouse = totHouse.Add(p.HousingLevy)
	}
	rep.Totals = map[string]any{
		"count": len(slips), "paye": money(totPaye), "shif_nhif": money(totShif),
		"nssf_employee": money(totNssfE), "nssf_employer": money(totNssfR), "housing_levy": money(totHouse),
	}
	return rep, nil
}

// BankSchedule is the bank net-pay disbursement list: employee + primary bank account + net.
func (s *Service) BankSchedule(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	banks, err := s.primaryBankMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	rep := &Report{
		Report:  "bank_schedule",
		Period:  periodMeta(f),
		Columns: []string{"employee", "bank_name", "branch_name", "account_number", "net_pay"},
		Rows:    []map[string]any{},
	}
	total := d()
	for _, p := range slips {
		ba := banks[p.EmployeeID]
		row := map[string]any{"employee": empName(emps[p.EmployeeID]), "net_pay": money(p.NetPay)}
		if ba != nil {
			row["bank_name"] = ba.BankName
			row["branch_name"] = ba.BranchName
			row["account_number"] = ba.AccountNumber
		}
		rep.Rows = append(rep.Rows, row)
		total = total.Add(p.NetPay)
	}
	rep.Totals = map[string]any{"count": len(slips), "net_pay": money(total)}
	return rep, nil
}

// PayrollVariance compares this period's per-employee net pay with the previous period.
func (s *Service) PayrollVariance(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	cur, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	span := f.End.Sub(f.Start)
	prevF := Filter{Start: f.Start.Add(-span), End: f.Start, OutletID: f.OutletID}
	prev, err := s.fetchPayslips(ctx, tenantID, prevF)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	prevNet := map[uuid.UUID]decimal.Decimal{}
	for _, p := range prev {
		prevNet[p.EmployeeID] = p.NetPay
	}
	rep := &Report{
		Report:  "payroll_variance",
		Period:  periodMeta(f),
		Columns: []string{"employee", "previous_net", "current_net", "variance"},
		Rows:    []map[string]any{},
	}
	for _, p := range cur {
		pv := prevNet[p.EmployeeID]
		rep.Rows = append(rep.Rows, map[string]any{
			"employee":     empName(emps[p.EmployeeID]),
			"previous_net": money(pv),
			"current_net":  money(p.NetPay),
			"variance":     money(p.NetPay.Sub(pv)),
		})
	}
	rep.Totals = map[string]any{"count": len(cur)}
	return rep, nil
}

func pin(e *ent.Employee) string {
	if e == nil {
		return ""
	}
	return e.PinNo
}

func natID(e *ent.Employee) string {
	if e == nil {
		return ""
	}
	return e.NationalID
}
