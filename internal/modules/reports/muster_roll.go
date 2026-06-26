package reports

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
)

// MusterRoll is the per-employee payroll sign-off sheet for the period: employee number + name,
// basic pay, gross, total deductions and net. Basic pay is sourced from the itemised payslip_line
// "basic" row (falling back to gross when a payslip predates itemisation). It matches the erp-ui
// report-runner's muster-roll column contract (employee_number, employee_name, department_name,
// basic_salary, gross_pay, total_deductions, net_pay). Dynamic per-component columns + Edit-Columns
// are a follow-up (needs report-runner support for backend-driven columns).
func (s *Service) MusterRoll(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}

	// basicByPayslip: the "Basic Pay" line per payslip (itemised runs only).
	basicByPayslip := map[uuid.UUID]decimal.Decimal{}
	ids := make([]uuid.UUID, 0, len(slips))
	for _, p := range slips {
		ids = append(ids, p.ID)
	}
	if len(ids) > 0 {
		lines, err := s.orm.PayslipLine.Query().
			Where(payslipline.TenantID(tenantID), payslipline.PayslipIDIn(ids...), payslipline.Code("basic")).
			All(ctx)
		if err != nil {
			return nil, err
		}
		for _, l := range lines {
			basicByPayslip[l.PayslipID] = basicByPayslip[l.PayslipID].Add(l.CashAmount)
		}
	}

	rep := &Report{
		Report: "Muster Roll",
		Period: periodMeta(f),
		Columns: []string{
			"employee_number", "employee_name", "department_name",
			"basic_salary", "gross_pay", "total_deductions", "net_pay",
		},
		Rows: []map[string]any{},
	}
	totBasic, totGross, totDed, totNet := d(), d(), d(), d()
	for _, p := range slips {
		e := emps[p.EmployeeID]
		basic, ok := basicByPayslip[p.ID]
		if !ok {
			basic = p.GrossPay // pre-itemisation payslip: best-effort
		}
		deductions := p.GrossPay.Sub(p.NetPay)
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_number":  empNumber(e),
			"employee_name":    empName(e),
			"department_name":  "",
			"basic_salary":     money(basic),
			"gross_pay":        money(p.GrossPay),
			"total_deductions": money(deductions),
			"net_pay":          money(p.NetPay),
		})
		totBasic = totBasic.Add(basic)
		totGross = totGross.Add(p.GrossPay)
		totDed = totDed.Add(deductions)
		totNet = totNet.Add(p.NetPay)
	}
	rep.Totals = map[string]any{
		"count":            len(slips),
		"basic_salary":     money(totBasic),
		"gross_pay":        money(totGross),
		"total_deductions": money(totDed),
		"net_pay":          money(totNet),
	}
	return rep, nil
}

// empNumber returns the employee's HR/payroll number (blank when unset).
func empNumber(e *ent.Employee) string {
	if e == nil || e.EmployeeNumber == nil {
		return ""
	}
	return *e.EmployeeNumber
}
