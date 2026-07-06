package reports

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebankaccount"
	"github.com/Bengo-Hub/erp-api/internal/ent/generalhrsettings"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
)

// nitaPerEmployee is the default monthly NITA Industrial Training Levy per employee (KES).
var nitaPerEmployee = decimal.NewFromInt(50)

// SHIF is the Social Health Insurance Fund return (2024+): per-employee SHIF/NHIF contribution.
func (s *Service) SHIF(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	return s.singleStatutory(ctx, tenantID, f, "shif", "shif_nhif", func(p *ent.Payslip) decimal.Decimal {
		return p.ShifOrNhifContribution
	})
}

// NHIF is the legacy NHIF return (same source column; cutover is config-driven in payroll).
func (s *Service) NHIF(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	return s.singleStatutory(ctx, tenantID, f, "nhif", "nhif", func(p *ent.Payslip) decimal.Decimal {
		return p.ShifOrNhifContribution
	})
}

// NSSF is the National Social Security Fund return: tier 1/2 employee + employer.
func (s *Service) NSSF(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	rep := &Report{
		Report:  "nssf",
		Period:  periodMeta(f),
		Columns: []string{"employee", "nssf_number", "tier_1", "tier_2", "employee_total", "employer", "total"},
		Rows:    []map[string]any{},
	}
	totE, totR := d(), d()
	for _, p := range slips {
		e := emps[p.EmployeeID]
		empTotal := p.NssfEmployeeTier1.Add(p.NssfEmployeeTier2)
		total := empTotal.Add(p.NssfEmployerContribution)
		nssfNo := ""
		if e != nil {
			nssfNo = e.NssfNo
		}
		rep.Rows = append(rep.Rows, map[string]any{
			"employee":       empName(e),
			"nssf_number":    nssfNo,
			"tier_1":         money(p.NssfEmployeeTier1),
			"tier_2":         money(p.NssfEmployeeTier2),
			"employee_total": money(empTotal),
			"employer":       money(p.NssfEmployerContribution),
			"total":          money(total),
		})
		totE = totE.Add(empTotal)
		totR = totR.Add(p.NssfEmployerContribution)
	}
	rep.Totals = map[string]any{
		"count": len(slips), "employee_total": money(totE),
		"employer": money(totR), "total": money(totE.Add(totR)),
	}
	return rep, nil
}

// HousingLevy is the Affordable Housing Levy return: 1.5% employee matched by 1.5% employer.
// The payslip stores the employee side; the employer match equals it (matched contribution).
func (s *Service) HousingLevy(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	rep := &Report{
		Report:  "housing-levy",
		Period:  periodMeta(f),
		Columns: []string{"employee_name", "employee_pin", "gross_pay", "employee_levy", "employer_levy", "total_levy"},
		Rows:    []map[string]any{},
	}
	totEmp, totEmpr := d(), d()
	for _, p := range slips {
		e := emps[p.EmployeeID]
		emp := p.HousingLevy
		empr := p.HousingLevy // matched 1.5%
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name": empName(e),
			"employee_pin":  pin(e),
			"gross_pay":     money(p.GrossPay),
			"employee_levy": money(emp),
			"employer_levy": money(empr),
			"total_levy":    money(emp.Add(empr)),
		})
		totEmp = totEmp.Add(emp)
		totEmpr = totEmpr.Add(empr)
	}
	rep.Totals = map[string]any{
		"count": len(slips), "employee_levy": money(totEmp),
		"employer_levy": money(totEmpr), "total_levy": money(totEmp.Add(totEmpr)),
	}
	return rep, nil
}

// NITA is the Industrial Training Levy return: a flat per-employee monthly levy
// (employer-only). The levy is read from each payslip's itemised "nita" employer line
// (formula-driven); legacy payslips processed before that line existed fall back to the
// default KES 50. Tenants that disabled NITA in statutory settings get an empty return.
func (s *Service) NITA(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	rep := &Report{
		Report:  "nita",
		Period:  periodMeta(f),
		Columns: []string{"employee", "levy"},
		Rows:    []map[string]any{},
	}
	if enabled, err := s.nitaEnabled(ctx, tenantID); err != nil {
		return nil, err
	} else if !enabled {
		rep.Totals = map[string]any{"count": 0, "levy": money(d())}
		return rep, nil
	}
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	levies, err := s.nitaLineAmounts(ctx, tenantID, slips)
	if err != nil {
		return nil, err
	}
	total := d()
	for _, p := range slips {
		levy := nitaPerEmployee
		if v, ok := levies[p.ID]; ok {
			levy = v
		}
		rep.Rows = append(rep.Rows, map[string]any{
			"employee": empName(emps[p.EmployeeID]),
			"levy":     money(levy),
		})
		total = total.Add(levy)
	}
	rep.Totals = map[string]any{"count": len(slips), "levy": money(total)}
	return rep, nil
}

// nitaEnabled reads the tenant's NITA toggle (missing settings row = enabled).
func (s *Service) nitaEnabled(ctx context.Context, tenantID uuid.UUID) (bool, error) {
	g, err := s.orm.GeneralHRSettings.Query().
		Where(generalhrsettings.TenantID(tenantID)).Only(ctx)
	if ent.IsNotFound(err) {
		return true, nil
	}
	if err != nil {
		return false, err
	}
	return g.NitaEnabled, nil
}

// nitaLineAmounts maps payslip ID → itemised NITA employer amount for the given slips.
func (s *Service) nitaLineAmounts(ctx context.Context, tenantID uuid.UUID, slips []*ent.Payslip) (map[uuid.UUID]decimal.Decimal, error) {
	if len(slips) == 0 {
		return nil, nil
	}
	ids := make([]uuid.UUID, 0, len(slips))
	for _, p := range slips {
		ids = append(ids, p.ID)
	}
	lines, err := s.orm.PayslipLine.Query().
		Where(
			payslipline.TenantID(tenantID),
			payslipline.PayslipIDIn(ids...),
			payslipline.Code("nita"),
		).All(ctx)
	if err != nil {
		return nil, err
	}
	out := make(map[uuid.UUID]decimal.Decimal, len(lines))
	for _, l := range lines {
		out[l.PayslipID] = l.EmployerAmount
	}
	return out, nil
}

// WithholdingTax is the WHT return: per-employee PAYE withheld (the ERP withholds PAYE on
// emoluments; non-payroll WHT is treasury-owned and is NOT reported here).
func (s *Service) WithholdingTax(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	return s.singleStatutory(ctx, tenantID, f, "withholding_tax", "withheld", func(p *ent.Payslip) decimal.Decimal {
		return p.Paye
	})
}

// singleStatutory is the shared per-employee single-amount statutory report builder.
func (s *Service) singleStatutory(ctx context.Context, tenantID uuid.UUID, f Filter, name, amountKey string, amount func(*ent.Payslip) decimal.Decimal) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	rep := &Report{
		Report:  name,
		Period:  periodMeta(f),
		Columns: []string{"employee", amountKey},
		Rows:    []map[string]any{},
	}
	total := d()
	for _, p := range slips {
		amt := amount(p)
		rep.Rows = append(rep.Rows, map[string]any{"employee": empName(emps[p.EmployeeID]), amountKey: money(amt)})
		total = total.Add(amt)
	}
	rep.Totals = map[string]any{"count": len(slips), amountKey: money(total)}
	return rep, nil
}

// primaryBankMap returns the primary bank account per employee (for the bank schedule).
func (s *Service) primaryBankMap(ctx context.Context, tenantID uuid.UUID) (map[uuid.UUID]*ent.EmployeeBankAccount, error) {
	rows, err := s.orm.EmployeeBankAccount.Query().
		Where(employeebankaccount.TenantID(tenantID), employeebankaccount.IsPrimary(true)).All(ctx)
	if err != nil {
		return nil, err
	}
	m := make(map[uuid.UUID]*ent.EmployeeBankAccount, len(rows))
	for _, b := range rows {
		m[b.EmployeeID] = b
	}
	return m, nil
}
