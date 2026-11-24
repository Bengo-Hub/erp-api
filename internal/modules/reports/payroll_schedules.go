package reports

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// bankColumns are the Bank Net Pay row keys (one row per disbursing bank), as read by the
// erp-ui report page; bankDetailColumns are the per-employee EFT lines in the Excel export.
var (
	bankColumns       = []string{"bank_name", "bank_code", "employee_count", "account_count", "total_net_pay", "reference_number"}
	bankDetailColumns = []string{"employee_number", "employee_name", "bank_name", "branch_name", "account_name", "account_number", "net_pay", "reference_number"}
)

// noBankAccount labels the group of payslips whose employee has no primary bank account.
const noBankAccount = "No bank account on file"

type bankGroup struct {
	name, code string
	employees  map[uuid.UUID]bool
	accounts   map[string]bool
	net        decimal.Decimal
	detail     []map[string]any
}

// BankSchedule is the bank net-pay schedule for EFT processing: net pay grouped by each
// employee's primary bank, with a batch reference per bank. The Excel export adds a sheet of
// the individual employee lines behind each bank total.
func (s *Service) BankSchedule(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID, slips)
	if err != nil {
		return nil, err
	}
	banks, err := s.primaryBankMap(ctx, tenantID, slips)
	if err != nil {
		return nil, err
	}

	groups := map[string]*bankGroup{}
	for _, p := range slips {
		ba := banks[p.EmployeeID]
		key, name, code := "", noBankAccount, ""
		if ba != nil {
			name, code = strings.TrimSpace(ba.BankName), strings.TrimSpace(ba.BankCode)
			key = strings.ToUpper(code)
			if key == "" {
				key = strings.ToUpper(name)
			}
			if name == "" {
				name = code
			}
		}
		g := groups[key]
		if g == nil {
			g = &bankGroup{name: name, code: code, employees: map[uuid.UUID]bool{}, accounts: map[string]bool{}}
			groups[key] = g
		}
		g.employees[p.EmployeeID] = true
		line := map[string]any{
			"employee_number": empNumber(emps[p.EmployeeID]),
			"employee_name":   empName(emps[p.EmployeeID]),
			"bank_name":       name,
			"net_pay":         money(p.NetPay),
		}
		if ba != nil {
			g.accounts[ba.AccountNumber] = true
			line["branch_name"] = ba.BranchName
			line["account_name"] = ba.AccountName
			line["account_number"] = ba.AccountNumber
		}
		g.detail = append(g.detail, line)
		g.net = g.net.Add(p.NetPay)
	}

	keys := make([]string, 0, len(groups))
	for k := range groups {
		keys = append(keys, k)
	}
	// Banks alphabetically; payslips without a bank account last so they stand out.
	sort.Slice(keys, func(i, j int) bool {
		if (keys[i] == "") != (keys[j] == "") {
			return keys[j] == ""
		}
		return strings.ToUpper(groups[keys[i]].name) < strings.ToUpper(groups[keys[j]].name)
	})

	rep := &Report{
		Report:  "bank_schedule",
		Period:  periodMeta(f),
		Columns: bankColumns,
		Rows:    []map[string]any{},
	}
	detail := ReportSheet{Name: "Employees", Columns: bankDetailColumns, Rows: []map[string]any{}}
	employees, accounts, total := 0, 0, d()
	for i, k := range keys {
		g := groups[k]
		ref := fmt.Sprintf("NET-%s-%02d", f.Start.Format("200601"), i+1)
		rep.Rows = append(rep.Rows, map[string]any{
			"bank_name":        g.name,
			"bank_code":        g.code,
			"employee_count":   len(g.employees),
			"account_count":    len(g.accounts),
			"total_net_pay":    money(g.net),
			"reference_number": ref,
		})
		for _, line := range g.detail {
			line["reference_number"] = ref
			detail.Rows = append(detail.Rows, line)
		}
		employees += len(g.employees)
		accounts += len(g.accounts)
		total = total.Add(g.net)
	}
	rep.Totals = map[string]any{
		"count": len(slips), "employee_count": employees, "account_count": accounts, "total_net_pay": money(total),
	}
	detail.Totals = map[string]any{"employee_number": "TOTAL", "net_pay": money(total)}
	rep.Sheets = []ReportSheet{
		{Name: "Banks", Columns: bankColumns, Rows: rep.Rows, Totals: rep.Totals},
		detail,
	}
	return rep, nil
}

// varianceColumns are the Payroll Variance row keys (one row per payroll category).
var (
	varianceColumns       = []string{"variance_category", "current_period", "previous_period", "variance_amount", "variance_percent", "variance_type"}
	varianceDetailColumns = []string{"employee_number", "employee_name", "previous_net", "current_net", "variance", "variance_type"}
)

// payrollTotals is one period's payroll summed over its payslips.
type payrollTotals struct {
	gross, paye, nssfEmployee, nssfEmployer, shif, housing, deductions, net decimal.Decimal
	headcount                                                               int
}

func sumPayroll(slips []*ent.Payslip) payrollTotals {
	var t payrollTotals
	seen := map[uuid.UUID]bool{}
	for _, p := range slips {
		seen[p.EmployeeID] = true
		t.gross = t.gross.Add(p.GrossPay)
		t.paye = t.paye.Add(p.Paye)
		t.nssfEmployee = t.nssfEmployee.Add(p.NssfEmployeeTier1).Add(p.NssfEmployeeTier2)
		t.nssfEmployer = t.nssfEmployer.Add(p.NssfEmployerContribution)
		t.shif = t.shif.Add(p.ShifOrNhifContribution)
		t.housing = t.housing.Add(p.HousingLevy)
		t.deductions = t.deductions.Add(p.GrossPay.Sub(p.NetPay))
		t.net = t.net.Add(p.NetPay)
	}
	t.headcount = len(seen)
	return t
}

// previousPeriod is the window just before f: the previous calendar month for a monthly
// report, the previous year for an annual one, otherwise a window of the same length.
func previousPeriod(f Filter) Filter {
	prev := Filter{End: f.Start, OutletID: f.OutletID}
	switch {
	case f.End.Equal(f.Start.AddDate(0, 1, 0)):
		prev.Start = f.Start.AddDate(0, -1, 0)
	case f.End.Equal(f.Start.AddDate(1, 0, 0)):
		prev.Start = f.Start.AddDate(-1, 0, 0)
	default:
		prev.Start = f.Start.Add(-f.End.Sub(f.Start))
	}
	return prev
}

// varianceType classifies a movement from prev to cur.
func varianceType(cur, prev decimal.Decimal) string {
	switch {
	case prev.IsZero() && !cur.IsZero():
		return "New"
	case cur.GreaterThan(prev):
		return "Increase"
	case cur.LessThan(prev):
		return "Decrease"
	default:
		return "No change"
	}
}

// varianceRow is one category row; the percentage is nil when there is nothing to compare to.
func varianceRow(category string, cur, prev decimal.Decimal) map[string]any {
	var pct any
	if !prev.IsZero() {
		pct = cur.Sub(prev).Div(prev.Abs()).Mul(decimal.NewFromInt(100)).StringFixed(2)
	}
	return map[string]any{
		"variance_category": category,
		"current_period":    money(cur),
		"previous_period":   money(prev),
		"variance_amount":   money(cur.Sub(prev)),
		"variance_percent":  pct,
		"variance_type":     varianceType(cur, prev),
	}
}

// PayrollVariance compares this period's payroll with the previous one, category by category
// (gross, statutory deductions, net). The Excel export adds the per-employee net pay movement.
func (s *Service) PayrollVariance(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	cur, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	prevF := previousPeriod(f)
	prev, err := s.fetchPayslips(ctx, tenantID, prevF)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID, cur, prev)
	if err != nil {
		return nil, err
	}

	c, p := sumPayroll(cur), sumPayroll(prev)
	rep := &Report{
		Report:  "payroll_variance",
		Period:  periodMeta(f),
		Columns: varianceColumns,
		Rows: []map[string]any{
			varianceRow("Gross Pay", c.gross, p.gross),
			varianceRow("PAYE", c.paye, p.paye),
			varianceRow("NSSF (Employee)", c.nssfEmployee, p.nssfEmployee),
			varianceRow("NSSF (Employer)", c.nssfEmployer, p.nssfEmployer),
			varianceRow("SHIF / NHIF", c.shif, p.shif),
			varianceRow("Housing Levy", c.housing, p.housing),
			varianceRow("Total Deductions", c.deductions, p.deductions),
			varianceRow("Net Pay", c.net, p.net),
		},
	}
	rep.Totals = map[string]any{
		"count":              len(cur),
		"current_headcount":  c.headcount,
		"previous_headcount": p.headcount,
		"previous_start":     prevF.Start.Format("2006-01-02"),
		"previous_end":       prevF.End.Format("2006-01-02"),
	}

	// Per-employee net pay movement, including people paid only in one of the two periods.
	curNet, prevNet := map[uuid.UUID]decimal.Decimal{}, map[uuid.UUID]decimal.Decimal{}
	order := []uuid.UUID{}
	for _, sl := range cur {
		if _, ok := curNet[sl.EmployeeID]; !ok {
			order = append(order, sl.EmployeeID)
		}
		curNet[sl.EmployeeID] = curNet[sl.EmployeeID].Add(sl.NetPay)
	}
	for _, sl := range prev {
		if _, ok := curNet[sl.EmployeeID]; !ok {
			if _, seen := prevNet[sl.EmployeeID]; !seen {
				order = append(order, sl.EmployeeID)
			}
		}
		prevNet[sl.EmployeeID] = prevNet[sl.EmployeeID].Add(sl.NetPay)
	}
	detail := ReportSheet{Name: "By Employee", Columns: varianceDetailColumns, Rows: []map[string]any{}}
	for _, id := range order {
		cn, pn := curNet[id], prevNet[id]
		detail.Rows = append(detail.Rows, map[string]any{
			"employee_number": empNumber(emps[id]),
			"employee_name":   empName(emps[id]),
			"previous_net":    money(pn),
			"current_net":     money(cn),
			"variance":        money(cn.Sub(pn)),
			"variance_type":   varianceType(cn, pn),
		})
	}
	detail.Totals = map[string]any{"employee_number": "TOTAL", "previous_net": money(p.net), "current_net": money(c.net), "variance": money(c.net.Sub(p.net))}
	rep.Sheets = []ReportSheet{
		{Name: "Summary", Columns: varianceColumns, Rows: rep.Rows},
		detail,
	}
	return rep, nil
}
