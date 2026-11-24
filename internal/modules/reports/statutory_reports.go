package reports

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebankaccount"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// nitaPerEmployee is the default monthly NITA Industrial Training Levy per employee (KES).
var nitaPerEmployee = decimal.NewFromInt(50)

// SHIF is the Social Health Insurance Fund return (2024+): per-employee SHIF/NHIF contribution.
func (s *Service) SHIF(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	return s.singleStatutory(ctx, tenantID, f, "shif", "shif_number", "shif_contribution", func(p *ent.Payslip) decimal.Decimal {
		return p.ShifOrNhifContribution
	})
}

// NHIF is the legacy NHIF return (same source column; cutover is config-driven in payroll).
func (s *Service) NHIF(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	return s.singleStatutory(ctx, tenantID, f, "nhif", "nhif_number", "nhif_contribution", func(p *ent.Payslip) decimal.Decimal {
		return p.ShifOrNhifContribution
	})
}

// NSSF is the National Social Security Fund return: tier 1/2 employee + employer.
func (s *Service) NSSF(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID, slips)
	if err != nil {
		return nil, err
	}
	rep := &Report{
		Report:  "nssf",
		Period:  periodMeta(f),
		Columns: nssfColumns,
		Rows:    []map[string]any{},
	}
	totGross, totT1, totT2, totE, totR := d(), d(), d(), d(), d()
	for _, p := range slips {
		e := emps[p.EmployeeID]
		empTotal := p.NssfEmployeeTier1.Add(p.NssfEmployeeTier2)
		nssfNo := ""
		if e != nil {
			nssfNo = e.NssfNo
		}
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name":     empName(e),
			"employee_pin":      pin(e),
			"nssf_number":       nssfNo,
			"gross_pay":         money(p.GrossPay),
			"tier_1":            money(p.NssfEmployeeTier1),
			"tier_2":            money(p.NssfEmployeeTier2),
			"employee_total":    money(empTotal),
			"employer":          money(p.NssfEmployerContribution),
			"nssf_contribution": money(empTotal.Add(p.NssfEmployerContribution)),
		})
		totGross = totGross.Add(p.GrossPay)
		totT1 = totT1.Add(p.NssfEmployeeTier1)
		totT2 = totT2.Add(p.NssfEmployeeTier2)
		totE = totE.Add(empTotal)
		totR = totR.Add(p.NssfEmployerContribution)
	}
	rep.Totals = map[string]any{
		"count": len(slips), "gross_pay": money(totGross), "tier_1": money(totT1), "tier_2": money(totT2),
		"employee_total": money(totE), "employer": money(totR), "nssf_contribution": money(totE.Add(totR)),
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
	emps, err := s.employeeMap(ctx, tenantID, slips)
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
// (employer-only). The levy is read from each payslip's itemised "nita" employer line, which
// is what the payroll run actually charged. A payslip without that line (processed before the
// line existed, or when no NITA formula resolved at run time) gets the tenant's configured
// levy, as long as NITA is enabled in statutory settings. Disabling NITA hides only the
// payslips that were never charged; a levy already on a payslip stays on the return.
func (s *Service) NITA(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	rep := &Report{
		Report:  "nita",
		Period:  periodMeta(f),
		Columns: nitaColumns,
		Rows:    []map[string]any{},
	}
	enabled, err := s.nitaEnabled(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	levies, err := s.nitaLineAmounts(ctx, tenantID, slips)
	if err != nil {
		return nil, err
	}
	charged := make([]*ent.Payslip, 0, len(slips))
	for _, p := range slips {
		if _, ok := levies[p.ID]; ok || enabled {
			charged = append(charged, p)
		}
	}
	emps, err := s.employeeMap(ctx, tenantID, charged)
	if err != nil {
		return nil, err
	}
	var fallback *decimal.Decimal
	totGross, total := d(), d()
	for _, p := range charged {
		levy, ok := levies[p.ID]
		if !ok {
			if fallback == nil {
				v := s.nitaConfiguredLevy(ctx, tenantID, f.Start)
				if v.IsZero() {
					v = nitaPerEmployee
				}
				fallback = &v
			}
			levy = *fallback
		}
		e := emps[p.EmployeeID]
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name": empName(e),
			"employee_pin":  pin(e),
			"gross_pay":     money(p.GrossPay),
			"nita_levy":     money(levy),
		})
		totGross = totGross.Add(p.GrossPay)
		total = total.Add(levy)
	}
	rep.Totals = map[string]any{
		"count": len(charged), "gross_pay": money(totGross), "nita_levy": money(total), "nita_enabled": enabled,
	}
	return rep, nil
}

// nitaEnabled reads the tenant's NITA toggle through the payroll settings resolver, the same
// rule payroll runs use (missing settings row = enabled).
func (s *Service) nitaEnabled(ctx context.Context, tenantID uuid.UUID) (bool, error) {
	return payrollsettings.NewService(s.orm, uuid.Nil).StatutoryEnabled(ctx, tenantID, payrollengine.CompNITA)
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
	out := make(map[uuid.UUID]decimal.Decimal, len(slips))
	for _, chunk := range idChunks(ids) {
		lines, err := s.orm.PayslipLine.Query().
			Where(
				payslipline.TenantID(tenantID),
				payslipline.PayslipIDIn(chunk...),
				payslipline.Code("nita"),
			).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, l := range lines {
			out[l.PayslipID] = out[l.PayslipID].Add(l.EmployerAmount)
		}
	}
	return out, nil
}

// singleStatutory is the shared per-employee single-amount statutory report builder.
// Each row carries the member's name, KRA PIN, national ID, health-scheme number (numberKey),
// gross pay, the contribution (amountKey) and whether it was an NHIF or SHIF deduction.
func (s *Service) singleStatutory(ctx context.Context, tenantID uuid.UUID, f Filter, name, numberKey, amountKey string, amount func(*ent.Payslip) decimal.Decimal) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID, slips)
	if err != nil {
		return nil, err
	}
	rep := &Report{
		Report:  name,
		Period:  periodMeta(f),
		Columns: healthColumns(numberKey, amountKey),
		Rows:    []map[string]any{},
	}
	totGross, total := d(), d()
	for _, p := range slips {
		e := emps[p.EmployeeID]
		amt := amount(p)
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name": empName(e),
			"employee_pin":  pin(e),
			"national_id":   natID(e),
			numberKey:       healthNumber(e),
			"gross_pay":     money(p.GrossPay),
			amountKey:       money(amt),
			"coverage_type": coverageType(p),
		})
		totGross = totGross.Add(p.GrossPay)
		total = total.Add(amt)
	}
	rep.Totals = map[string]any{"count": len(slips), "gross_pay": money(totGross), amountKey: money(total)}
	return rep, nil
}

// primaryBankMap returns the primary bank account of each employee on the payslips.
func (s *Service) primaryBankMap(ctx context.Context, tenantID uuid.UUID, slips []*ent.Payslip) (map[uuid.UUID]*ent.EmployeeBankAccount, error) {
	m := map[uuid.UUID]*ent.EmployeeBankAccount{}
	for _, chunk := range idChunks(slipEmployeeIDs(slips)) {
		rows, err := s.orm.EmployeeBankAccount.Query().
			Where(employeebankaccount.TenantID(tenantID), employeebankaccount.IsPrimary(true), employeebankaccount.EmployeeIDIn(chunk...)).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, r := range rows {
			m[r.EmployeeID] = r
		}
	}
	return m, nil
}
