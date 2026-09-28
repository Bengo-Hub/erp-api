package reports

import (
	"context"
	"fmt"
	"math"
	"time"

	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/timesheet"
	"github.com/Bengo-Hub/erp-api/internal/ent/timesheetentry"
)

// workforceFigures adds exits and turnover, overtime hours and leave liability, each one grouped
// or summed query (the cost does not grow with the number of employees or records).
func (s *Service) workforceFigures(ctx context.Context, tenantID uuid.UUID, from, to time.Time, out *HRMAnalytics) error {
	exits, err := s.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.Deleted(false), employee.Terminated(true),
			employee.TerminatedAtGTE(from), employee.TerminatedAtLTE(to)).
		Count(ctx)
	if err != nil {
		return fmt.Errorf("exits: %w", err)
	}
	out.Exits = exits
	out.TurnoverPct = turnoverPct(out.Headcount, exits, out.NewHires)

	sumHours := func(rows []struct {
		Hours decimal.Decimal `json:"hours"`
	}) decimal.Decimal {
		if len(rows) == 1 {
			return rows[0].Hours
		}
		return decimal.Zero
	}
	var att []struct {
		Hours decimal.Decimal `json:"hours"`
	}
	if err := s.orm.AttendanceRecord.Query().
		Where(attendancerecord.TenantID(tenantID), attendancerecord.DateGTE(from), attendancerecord.DateLTE(to)).
		Aggregate(sumAs("hours", attendancerecord.FieldOvertimeHours)).
		Scan(ctx, &att); err != nil {
		return fmt.Errorf("attendance overtime: %w", err)
	}
	out.OvertimeAttendanceHours = sumHours(att)

	var ts []struct {
		Hours decimal.Decimal `json:"hours"`
	}
	if err := s.orm.TimesheetEntry.Query().
		Where(timesheetentry.TenantID(tenantID), timesheetentry.DateGTE(from), timesheetentry.DateLTE(to)).
		Where(func(sel *entsql.Selector) {
			t := entsql.Table(timesheet.Table)
			sel.Where(entsql.In(sel.C(timesheetentry.FieldTimesheetID),
				entsql.Select(t.C(timesheet.FieldID)).From(t).
					Where(entsql.And(entsql.EQ(t.C(timesheet.FieldTenantID), tenantID), entsql.EQ(t.C(timesheet.FieldStatus), timesheet.StatusApproved)))))
		}).
		Aggregate(sumAs("hours", timesheetentry.FieldOvertimeHours)).
		Scan(ctx, &ts); err != nil {
		return fmt.Errorf("timesheet overtime: %w", err)
	}
	out.OvertimeTimesheetHours = sumHours(ts)

	// Leave liability: remaining days of this year's balances of active employees, valued at each
	// employee's daily rate from their active salary record (the payroll module derives it).
	var leave []struct {
		Days      decimal.Decimal `json:"days"`
		Liability decimal.Decimal `json:"liability"`
	}
	sd := entsql.Table(salarydetails.Table)
	if err := s.orm.LeaveBalance.Query().
		Where(leavebalance.TenantID(tenantID), leavebalance.Year(time.Now().Year()), leaveOfActiveEmployee(tenantID)).
		Where(func(sel *entsql.Selector) {
			// The active salary record joins in the ON clause, so an employee without one still
			// counts their days (valued at zero) instead of dropping out.
			sel.LeftJoin(sd).OnP(entsql.And(
				entsql.ColumnsEQ(sel.C(leavebalance.FieldEmployeeID), sd.C(salarydetails.FieldEmployeeID)),
				entsql.EQ(sd.C(salarydetails.FieldTenantID), tenantID),
				entsql.EQ(sd.C(salarydetails.FieldIsActive), true),
			))
		}).
		Aggregate(
			func(sel *entsql.Selector) string {
				return entsql.As(fmt.Sprintf("COALESCE(SUM(GREATEST(COALESCE(%s, 0), 0)), 0)", sel.C(leavebalance.FieldDaysRemaining)), "days")
			},
			func(sel *entsql.Selector) string {
				return entsql.As(fmt.Sprintf("COALESCE(SUM(GREATEST(COALESCE(%s, 0), 0) * COALESCE(%s, 0)), 0)",
					sel.C(leavebalance.FieldDaysRemaining), sd.C(salarydetails.FieldDailyRate)), "liability")
			},
		).
		Scan(ctx, &leave); err != nil {
		return fmt.Errorf("leave liability: %w", err)
	}
	if len(leave) == 1 {
		out.LeaveDaysRemaining, out.LeaveLiability = leave[0].Days, leave[0].Liability.Round(2)
	}
	return nil
}

// turnoverPct is exits over the average headcount of the period: headcount at the start is
// today's headcount plus the period's exits less its new hires. Nil when there is no headcount.
func turnoverPct(headcountEnd, exits, newHires int) *float64 {
	start := headcountEnd + exits - newHires
	avg := float64(start+headcountEnd) / 2
	if avg <= 0 {
		return nil
	}
	v := math.Round(float64(exits)/avg*1000) / 10
	return &v
}

// sumAs is COALESCE(SUM(col), 0) AS alias.
func sumAs(alias, column string) func(*entsql.Selector) string {
	return func(sel *entsql.Selector) string {
		return entsql.As(fmt.Sprintf("COALESCE(SUM(%s), 0)", sel.C(column)), alias)
	}
}

// leaveOfActiveEmployee limits leave balances to active employees through a sub-select.
func leaveOfActiveEmployee(tenantID uuid.UUID) func(*entsql.Selector) {
	return func(sel *entsql.Selector) {
		t := entsql.Table(employee.Table)
		sel.Where(entsql.In(sel.C(leavebalance.FieldEmployeeID),
			entsql.Select(t.C(employee.FieldID)).From(t).Where(entsql.And(
				entsql.EQ(t.C(employee.FieldTenantID), tenantID),
				entsql.EQ(t.C(employee.FieldDeleted), false),
				entsql.EQ(t.C(employee.FieldTerminated), false),
			))))
	}
}
