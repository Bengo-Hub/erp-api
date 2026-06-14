package reports

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebankaccount"
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

// NITA is the Industrial Training Levy return: a flat per-employee monthly levy.
func (s *Service) NITA(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	rep := &Report{
		Report:  "nita",
		Period:  periodMeta(f),
		Columns: []string{"employee", "levy"},
		Rows:    []map[string]any{},
	}
	total := d()
	for _, p := range slips {
		rep.Rows = append(rep.Rows, map[string]any{
			"employee": empName(emps[p.EmployeeID]),
			"levy":     money(nitaPerEmployee),
		})
		total = total.Add(nitaPerEmployee)
	}
	rep.Totals = map[string]any{"count": len(slips), "levy": money(total)}
	return rep, nil
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
