package reports

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
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
		a.net = a.net.Add(p.NetPay)
	}
	rep := &Report{
		Report:  "P9",
		Period:  periodMeta(f),
		Columns: []string{"employee_name", "employee_pin", "national_id", "total_gross_pay", "total_deductions", "chargeable_pay", "total_tax", "net_pay"},
		Rows:    []map[string]any{},
	}
	totChargeable, totPaye, totNet := d(), d(), d()
	for _, id := range order {
		a := byEmp[id]
		deductions := a.gross.Sub(a.net)
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name":    empName(a.e),
			"employee_pin":     pin(a.e),
			"national_id":      natID(a.e),
			"total_gross_pay":  money(a.gross),
			"total_deductions": money(deductions),
			"chargeable_pay":   money(a.taxable),
			"total_tax":        money(a.paye),
			"net_pay":          money(a.net),
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

// p10aAcc accumulates an employer-return row per employee across the period.
type p10aAcc struct {
	e                       *ent.Employee
	gross, paye, nssf, nhif decimal.Decimal
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
		a.nhif = a.nhif.Add(p.ShifOrNhifContribution)
	}
	rep := &Report{
		Report:  "P10A",
		Period:  periodMeta(f),
		Columns: []string{"employee_name", "employee_pin", "total_gross_pay", "total_paye", "total_nssf", "total_nhif"},
		Rows:    []map[string]any{},
	}
	totGross, totPaye := d(), d()
	for _, id := range order {
		a := byEmp[id]
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name":   empName(a.e),
			"employee_pin":    pin(a.e),
			"total_gross_pay": money(a.gross),
			"total_paye":      money(a.paye),
			"total_nssf":      money(a.nssf),
			"total_nhif":      money(a.nhif),
		})
		totGross = totGross.Add(a.gross)
		totPaye = totPaye.Add(a.paye)
	}
	rep.Totals = map[string]any{"count": len(order), "total_gross_pay": money(totGross), "total_paye": money(totPaye)}
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
