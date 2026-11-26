package reports

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	entsql "entgo.io/ent/dialect/sql"
	"entgo.io/ent/dialect/sql/sqljson"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/contract"
	"github.com/Bengo-Hub/erp-api/internal/ent/department"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/ent/predicate"
)

// HRMAnalytics feeds the HR and executive dashboards. Every figure is counted or summed in SQL
// (grouped queries), so the cost does not grow with the number of employees or payslips.
type HRMAnalytics struct {
	Headcount        int             `json:"headcount"` // active employees
	Terminated       int             `json:"terminated"`
	NewHires         int             `json:"new_hires"` // joined within the period
	ByDepartment     []NamedCount    `json:"by_department"`
	ByGender         []NamedCount    `json:"by_gender"`
	ByEmploymentType []NamedCount    `json:"by_employment_type"`
	ContractsExpiry  ContractsExpiry `json:"contracts_expiring"`
	PayrollTrend     []PayrollMonth  `json:"payroll_trend"`         // last 12 months
	PayrollByDept    []NamedAmount   `json:"payroll_by_department"` // latest payroll month
	PeriodFrom       string          `json:"period_from"`
	PeriodTo         string          `json:"period_to"`

	// Exits are employees terminated within the period (dated by terminated_at); TurnoverPct is
	// exits over the average headcount of the period, nil without a headcount.
	Exits       int      `json:"exits"`
	TurnoverPct *float64 `json:"turnover_pct"`
	// Overtime hours in the period, from clock-in attendance and from approved timesheets (kept
	// apart: a tenant normally uses one, and adding them could count the same hours twice).
	OvertimeAttendanceHours decimal.Decimal `json:"overtime_attendance_hours"`
	OvertimeTimesheetHours  decimal.Decimal `json:"overtime_timesheet_hours"`
	// LeaveLiability is this year's remaining leave days of active employees at their daily rate.
	LeaveLiability     decimal.Decimal `json:"leave_liability"`
	LeaveDaysRemaining decimal.Decimal `json:"leave_days_remaining"`
	// LoginDisabled are current employees whose login was disabled in auth-api: HR reviews
	// whether they have left (Mark as exited, final pay) or the login should be restored.
	LoginDisabled []LoginDisabledEmployee `json:"login_disabled"`
}

// LoginDisabledEmployee is one employee flagged "login disabled, review exit".
type LoginDisabledEmployee struct {
	EmployeeID     uuid.UUID `json:"employee_id"`
	Name           string    `json:"name"`
	EmployeeNumber string    `json:"employee_number,omitempty"`
	Status         string    `json:"status"`
	Since          string    `json:"since"`
}

// loginDisabled lists the tenant's current employees flagged by an auth-api deactivation.
func (s *Service) loginDisabled(ctx context.Context, tenantID uuid.UUID) ([]LoginDisabledEmployee, error) {
	rows, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.Deleted(false), employee.Terminated(false),
		func(sel *entsql.Selector) {
			sel.Where(sqljson.HasKey(employee.FieldMetadata, sqljson.Path("login_disabled_at")))
		}).
		Order(employee.ByFirstName()).Limit(200).All(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]LoginDisabledEmployee, 0, len(rows))
	for _, e := range rows {
		v := LoginDisabledEmployee{EmployeeID: e.ID, Name: strings.TrimSpace(e.FirstName + " " + e.LastName)}
		if e.EmployeeNumber != nil {
			v.EmployeeNumber = *e.EmployeeNumber
		}
		v.Status, _ = e.Metadata["login_status"].(string)
		v.Since, _ = e.Metadata["login_disabled_at"].(string)
		out = append(out, v)
	}
	return out, nil
}

// NamedCount is one group of a headcount breakdown.
type NamedCount struct {
	Key   string `json:"key"`
	Label string `json:"label"`
	Count int    `json:"count"`
}

// NamedAmount is one group of a money breakdown.
type NamedAmount struct {
	Key    string          `json:"key"`
	Label  string          `json:"label"`
	Amount decimal.Decimal `json:"amount"`
}

// ContractsExpiry counts active contracts ending within 30, 60 and 90 days.
type ContractsExpiry struct {
	Within30 int `json:"within_30_days"`
	Within60 int `json:"within_60_days"`
	Within90 int `json:"within_90_days"`
}

// PayrollMonth is one month of payroll cost.
type PayrollMonth struct {
	Month     string          `json:"month"`
	Gross     decimal.Decimal `json:"gross"`
	Net       decimal.Decimal `json:"net"`
	Employees int             `json:"employees"`
}

// activeEmployeeOf limits HR detail rows to active (not terminated, not deleted) employees
// through a sub-select, so the grouping still happens in one statement.
func activeEmployeeOf(tenantID uuid.UUID) predicate.HRDetails {
	return func(s *entsql.Selector) {
		t := entsql.Table(employee.Table)
		s.Where(entsql.In(s.C(hrdetails.FieldEmployeeID),
			entsql.Select(t.C(employee.FieldID)).From(t).Where(entsql.And(
				entsql.EQ(t.C(employee.FieldTenantID), tenantID),
				entsql.EQ(t.C(employee.FieldDeleted), false),
				entsql.EQ(t.C(employee.FieldTerminated), false),
			))))
	}
}

// HRMAnalytics builds the dashboard figures; from/to bound "new hires".
func (s *Service) HRMAnalytics(ctx context.Context, tenantID uuid.UUID, from, to time.Time) (*HRMAnalytics, error) {
	out := &HRMAnalytics{PeriodFrom: from.Format("2006-01-02"), PeriodTo: to.Format("2006-01-02")}

	var status []struct {
		Terminated bool `json:"terminated"`
		Count      int  `json:"count"`
	}
	if err := s.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.Deleted(false)).
		GroupBy(employee.FieldTerminated).Aggregate(entCount()).Scan(ctx, &status); err != nil {
		return nil, fmt.Errorf("headcount: %w", err)
	}
	for _, r := range status {
		if r.Terminated {
			out.Terminated = r.Count
		} else {
			out.Headcount = r.Count
		}
	}

	var genders []struct {
		Gender *string `json:"gender"`
		Count  int     `json:"count"`
	}
	if err := s.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.Deleted(false), employee.Terminated(false)).
		GroupBy(employee.FieldGender).Aggregate(entCount()).Scan(ctx, &genders); err != nil {
		return nil, fmt.Errorf("gender: %w", err)
	}
	for _, g := range genders {
		k := deref(g.Gender)
		out.ByGender = append(out.ByGender, NamedCount{Key: k, Label: labelOr(k, "Not set"), Count: g.Count})
	}

	var types []struct {
		EmploymentType *string `json:"employment_type"`
		Count          int     `json:"count"`
	}
	if err := s.orm.HRDetails.Query().
		Where(hrdetails.TenantID(tenantID), activeEmployeeOf(tenantID)).
		GroupBy(hrdetails.FieldEmploymentType).Aggregate(entCount()).Scan(ctx, &types); err != nil {
		return nil, fmt.Errorf("employment type: %w", err)
	}
	for _, t := range types {
		k := deref(t.EmploymentType)
		out.ByEmploymentType = append(out.ByEmploymentType, NamedCount{Key: k, Label: labelOr(k, "Not set"), Count: t.Count})
	}

	var depts []struct {
		DepartmentID *uuid.UUID `json:"department_id"`
		Count        int        `json:"count"`
	}
	if err := s.orm.HRDetails.Query().
		Where(hrdetails.TenantID(tenantID), activeEmployeeOf(tenantID)).
		GroupBy(hrdetails.FieldDepartmentID).Aggregate(entCount()).Scan(ctx, &depts); err != nil {
		return nil, fmt.Errorf("department: %w", err)
	}
	names, err := s.departmentNames(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	for _, d := range depts {
		key, label := "", "No department"
		if d.DepartmentID != nil {
			key, label = d.DepartmentID.String(), labelOr(names[*d.DepartmentID], d.DepartmentID.String())
		}
		out.ByDepartment = append(out.ByDepartment, NamedCount{Key: key, Label: label, Count: d.Count})
	}
	sort.Slice(out.ByDepartment, func(i, j int) bool { return out.ByDepartment[i].Count > out.ByDepartment[j].Count })

	if out.NewHires, err = s.orm.HRDetails.Query().
		Where(hrdetails.TenantID(tenantID), hrdetails.DateJoinedGTE(from), hrdetails.DateJoinedLTE(to), activeEmployeeOf(tenantID)).
		Count(ctx); err != nil {
		return nil, fmt.Errorf("new hires: %w", err)
	}

	now := time.Now()
	expiring := func(days int) (int, error) {
		return s.orm.Contract.Query().
			Where(contract.TenantID(tenantID), contract.Status("active"),
				contract.EndDateGTE(now), contract.EndDateLTE(now.AddDate(0, 0, days))).
			Count(ctx)
	}
	if out.ContractsExpiry.Within30, err = expiring(30); err != nil {
		return nil, err
	}
	if out.ContractsExpiry.Within60, err = expiring(60); err != nil {
		return nil, err
	}
	if out.ContractsExpiry.Within90, err = expiring(90); err != nil {
		return nil, err
	}

	if err := s.workforceFigures(ctx, tenantID, from, to, out); err != nil {
		return nil, err
	}

	if out.PayrollTrend, err = s.payrollTrend(ctx, tenantID, now); err != nil {
		return nil, err
	}
	if len(out.PayrollTrend) > 0 {
		if out.PayrollByDept, err = s.payrollByDepartment(ctx, tenantID, out.PayrollTrend[len(out.PayrollTrend)-1].Month, names); err != nil {
			return nil, err
		}
	}
	if out.LoginDisabled, err = s.loginDisabled(ctx, tenantID); err != nil {
		return nil, fmt.Errorf("login disabled: %w", err)
	}
	return out, nil
}

func entCount() func(*entsql.Selector) string {
	return func(s *entsql.Selector) string { return entsql.As("COUNT(*)", "count") }
}

func labelOr(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}

func (s *Service) departmentNames(ctx context.Context, tenantID uuid.UUID) (map[uuid.UUID]string, error) {
	var rows []struct {
		ID    uuid.UUID `json:"id"`
		Title string    `json:"title"`
	}
	if err := s.orm.Department.Query().
		Where(department.Or(department.TenantID(tenantID), department.TenantIDIsNil())).
		Select(department.FieldID, department.FieldTitle).Scan(ctx, &rows); err != nil {
		return nil, fmt.Errorf("departments: %w", err)
	}
	out := make(map[uuid.UUID]string, len(rows))
	for _, r := range rows {
		out[r.ID] = r.Title
	}
	return out, nil
}

// payrollTrend sums payslips per payment month over the last 12 months in SQL.
func (s *Service) payrollTrend(ctx context.Context, tenantID uuid.UUID, now time.Time) ([]PayrollMonth, error) {
	monthExpr := func(sel *entsql.Selector) string {
		return fmt.Sprintf("to_char(%s, 'YYYY-MM')", sel.C(payslip.FieldPaymentPeriod))
	}
	var rows []struct {
		Month     string          `json:"month"`
		Gross     decimal.Decimal `json:"gross"`
		Net       decimal.Decimal `json:"net"`
		Employees int             `json:"employees"`
	}
	err := s.orm.Payslip.Query().
		Where(payslip.TenantID(tenantID), payslip.DeleteStatus(false),
			payslip.PaymentPeriodNotNil(), payslip.PaymentPeriodGTE(now.AddDate(-1, 0, 0))).
		Where(func(sel *entsql.Selector) { sel.GroupBy(monthExpr(sel)) }).
		Aggregate(
			func(sel *entsql.Selector) string { return entsql.As(monthExpr(sel), "month") },
			func(sel *entsql.Selector) string {
				return entsql.As(fmt.Sprintf("COALESCE(SUM(%s), 0)", sel.C(payslip.FieldGrossPay)), "gross")
			},
			func(sel *entsql.Selector) string {
				return entsql.As(fmt.Sprintf("COALESCE(SUM(%s), 0)", sel.C(payslip.FieldNetPay)), "net")
			},
			func(sel *entsql.Selector) string {
				return entsql.As(fmt.Sprintf("COUNT(DISTINCT %s)", sel.C(payslip.FieldEmployeeID)), "employees")
			},
		).
		Scan(ctx, &rows)
	if err != nil {
		return nil, fmt.Errorf("payroll trend: %w", err)
	}
	out := make([]PayrollMonth, len(rows))
	for i, r := range rows {
		out[i] = PayrollMonth(r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Month < out[j].Month })
	return out, nil
}

// payrollByDepartment sums one month's gross pay per department: payslips are summed per
// employee in SQL, then placed on each employee's department.
func (s *Service) payrollByDepartment(ctx context.Context, tenantID uuid.UUID, month string, names map[uuid.UUID]string) ([]NamedAmount, error) {
	start, err := time.Parse("2006-01", month)
	if err != nil {
		return nil, nil
	}
	var perEmp []struct {
		EmployeeID uuid.UUID       `json:"employee_id"`
		Gross      decimal.Decimal `json:"gross"`
	}
	if err := s.orm.Payslip.Query().
		Where(payslip.TenantID(tenantID), payslip.DeleteStatus(false),
			payslip.PaymentPeriodGTE(start), payslip.PaymentPeriodLT(start.AddDate(0, 1, 0))).
		GroupBy(payslip.FieldEmployeeID).
		Aggregate(func(sel *entsql.Selector) string {
			return entsql.As(fmt.Sprintf("COALESCE(SUM(%s), 0)", sel.C(payslip.FieldGrossPay)), "gross")
		}).
		Scan(ctx, &perEmp); err != nil {
		return nil, fmt.Errorf("payroll by employee: %w", err)
	}
	if len(perEmp) == 0 {
		return []NamedAmount{}, nil
	}
	ids := make([]uuid.UUID, len(perEmp))
	for i, p := range perEmp {
		ids[i] = p.EmployeeID
	}
	var hr []struct {
		EmployeeID   uuid.UUID  `json:"employee_id"`
		DepartmentID *uuid.UUID `json:"department_id"`
	}
	if err := s.orm.HRDetails.Query().
		Where(hrdetails.TenantID(tenantID), hrdetails.EmployeeIDIn(ids...)).
		Select(hrdetails.FieldEmployeeID, hrdetails.FieldDepartmentID).Scan(ctx, &hr); err != nil {
		return nil, fmt.Errorf("employee departments: %w", err)
	}
	deptOf := make(map[uuid.UUID]*uuid.UUID, len(hr))
	for _, h := range hr {
		deptOf[h.EmployeeID] = h.DepartmentID
	}
	sums := map[string]*NamedAmount{}
	for _, p := range perEmp {
		key, label := "", "No department"
		if d := deptOf[p.EmployeeID]; d != nil {
			key, label = d.String(), labelOr(names[*d], d.String())
		}
		na := sums[key]
		if na == nil {
			na = &NamedAmount{Key: key, Label: label}
			sums[key] = na
		}
		na.Amount = na.Amount.Add(p.Gross)
	}
	out := make([]NamedAmount, 0, len(sums))
	for _, v := range sums {
		out = append(out, *v)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Amount.GreaterThan(out[j].Amount) })
	return out, nil
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
