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

// P9 is the KRA Tax Deduction Card: per-employee gross, reliefs, taxable pay, PAYE.
func (s *Service) P9(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	rep := &Report{
		Report:  "P9",
		Period:  periodMeta(f),
		Columns: []string{"employee", "pin", "gross_pay", "shif_nhif", "nssf", "taxable_pay", "tax_relief", "paye", "net_pay"},
		Rows:    []map[string]any{},
	}
	totGross, totTaxable, totPaye, totNet := d(), d(), d(), d()
	for _, p := range slips {
		e := emps[p.EmployeeID]
		nssf := p.NssfEmployeeTier1.Add(p.NssfEmployeeTier2)
		rep.Rows = append(rep.Rows, map[string]any{
			"employee":    empName(e),
			"pin":         pin(e),
			"gross_pay":   money(p.GrossPay),
			"shif_nhif":   money(p.ShifOrNhifContribution),
			"nssf":        money(nssf),
			"taxable_pay": money(p.TaxablePay),
			"tax_relief":  money(p.TaxRelief),
			"paye":        money(p.Paye),
			"net_pay":     money(p.NetPay),
		})
		totGross = totGross.Add(p.GrossPay)
		totTaxable = totTaxable.Add(p.TaxablePay)
		totPaye = totPaye.Add(p.Paye)
		totNet = totNet.Add(p.NetPay)
	}
	rep.Totals = map[string]any{
		"count": len(slips), "gross_pay": money(totGross), "taxable_pay": money(totTaxable),
		"paye": money(totPaye), "net_pay": money(totNet),
	}
	return rep, nil
}

// P10A is the PAYE return: per-employee taxable pay, PAYE charged and relief.
func (s *Service) P10A(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	rep := &Report{
		Report:  "P10A",
		Period:  periodMeta(f),
		Columns: []string{"employee", "pin", "national_id", "taxable_pay", "tax_relief", "paye"},
		Rows:    []map[string]any{},
	}
	totTaxable, totPaye := d(), d()
	for _, p := range slips {
		e := emps[p.EmployeeID]
		rep.Rows = append(rep.Rows, map[string]any{
			"employee":    empName(e),
			"pin":         pin(e),
			"national_id": natID(e),
			"taxable_pay": money(p.TaxablePay),
			"tax_relief":  money(p.TaxRelief),
			"paye":        money(p.Paye),
		})
		totTaxable = totTaxable.Add(p.TaxablePay)
		totPaye = totPaye.Add(p.Paye)
	}
	rep.Totals = map[string]any{"count": len(slips), "taxable_pay": money(totTaxable), "paye": money(totPaye)}
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
