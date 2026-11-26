package attendance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshift"
)

var weeksPerMonth = decimal.NewFromInt(52).Div(decimal.NewFromInt(12))

// PayableTime is one employee's paid extra time for a payroll period.
type PayableTime struct {
	OvertimeHours      decimal.Decimal // on ordinary days, capped by approvals when required
	OvertimeMultiplier decimal.Decimal
	HolidayHours       decimal.Decimal // every hour worked on a public holiday
	HolidayMultiplier  decimal.Decimal
	MonthlyHours       decimal.Decimal // hours a monthly salary pays for: salary / this = hourly rate
}

// Amount is the pay for the extra time given a monthly salary: hourly rate times hours times
// the multiplier, overtime and holiday work separately. Pure.
func (p PayableTime) Amount(monthlySalary decimal.Decimal) (overtime, holiday decimal.Decimal) {
	if !p.MonthlyHours.IsPositive() || !monthlySalary.IsPositive() {
		return decimal.Zero, decimal.Zero
	}
	hourly := monthlySalary.Div(p.MonthlyHours)
	overtime = hourly.Mul(p.OvertimeHours).Mul(p.OvertimeMultiplier).Round(2)
	holiday = hourly.Mul(p.HolidayHours).Mul(p.HolidayMultiplier).Round(2)
	return overtime, holiday
}

// payableDay splits one record's hours into overtime and holiday hours. On a holiday every
// worked hour is holiday time; otherwise the overtime is capped by approved hours when the
// tenant requires approval. Pure.
func payableDay(regular, overtime decimal.Decimal, holiday, needApproval bool, approved decimal.Decimal) (ot, hol decimal.Decimal) {
	if holiday {
		return decimal.Zero, regular.Add(overtime)
	}
	if needApproval && overtime.GreaterThan(approved) {
		return approved, decimal.Zero
	}
	return overtime, decimal.Zero
}

// PayableTimeForPeriod returns, for the payroll month starting at period, each employee's
// overtime and holiday hours with the multipliers and hourly basis to pay them at. It is empty
// unless the tenant switched payroll_overtime_enabled on. Rates come from the employee's most
// specific overtime rule, else the tenant attendance settings.
func PayableTimeForPeriod(ctx context.Context, orm *ent.Client, tenantID uuid.UUID, period time.Time, empIDs []uuid.UUID) (map[uuid.UUID]PayableTime, error) {
	s := NewService(orm)
	out := map[uuid.UUID]PayableTime{}
	st, err := s.GetSettings(ctx, tenantID)
	if err != nil || !st.PayrollOvertimeEnabled || len(empIDs) == 0 {
		return out, err
	}
	from := dateOnly(period)
	from = time.Date(from.Year(), from.Month(), 1, 0, 0, 0, 0, time.UTC)
	to := from.AddDate(0, 1, 0)
	recs, err := orm.AttendanceRecord.Query().Where(attendancerecord.TenantID(tenantID),
		attendancerecord.EmployeeIDIn(empIDs...), attendancerecord.DateGTE(from), attendancerecord.DateLT(to),
		attendancerecord.Or(attendancerecord.OvertimeHoursGT(decimal.Zero), attendancerecord.RegularHoursGT(decimal.Zero)),
	).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: payable records: %w", err)
	}
	if len(recs) == 0 {
		return out, nil
	}
	approved := map[uuid.UUID]map[time.Time]decimal.Decimal{}
	if st.OvertimeRequiresApproval {
		if approved, err = s.ApprovedOvertime(ctx, tenantID, from, to.AddDate(0, 0, -1)); err != nil {
			return nil, err
		}
	}
	holidays, err := s.holidayDays(ctx, tenantID, from, to, empIDs)
	if err != nil {
		return nil, err
	}
	rules, err := s.loadRuleSet(ctx, tenantID, empIDs)
	if err != nil {
		return nil, err
	}
	basis, outlets, err := s.monthlyHours(ctx, tenantID, empIDs, st)
	if err != nil {
		return nil, err
	}
	for _, r := range recs {
		d := dateOnly(r.Date)
		ot, hol := payableDay(r.RegularHours, r.OvertimeHours, holidays(r.EmployeeID, d), st.OvertimeRequiresApproval, approved[r.EmployeeID][d])
		p, ok := out[r.EmployeeID]
		if !ok {
			p = PayableTime{OvertimeMultiplier: st.OTMultiplier, HolidayMultiplier: st.HolidayMultiplier, MonthlyHours: basis[r.EmployeeID]}
			if rule := rules.pick(r.EmployeeID, outlets[r.EmployeeID]); rule != nil {
				if rule.OvertimeRateMultiplier.IsPositive() {
					p.OvertimeMultiplier = rule.OvertimeRateMultiplier
				}
				if rule.HolidayPayMultiplier.IsPositive() {
					p.HolidayMultiplier = rule.HolidayPayMultiplier
				}
			}
		}
		p.OvertimeHours = p.OvertimeHours.Add(ot)
		p.HolidayHours = p.HolidayHours.Add(hol)
		out[r.EmployeeID] = p
	}
	for id, p := range out {
		if p.OvertimeHours.IsZero() && p.HolidayHours.IsZero() {
			delete(out, id)
		}
	}
	return out, nil
}

// holidayDays answers whether a day is a public holiday for an employee: national ones for
// everyone, county ones by the employee's county.
func (s *Service) holidayDays(ctx context.Context, tenantID uuid.UUID, from, to time.Time, empIDs []uuid.UUID) (func(uuid.UUID, time.Time) bool, error) {
	rows, err := s.publicHolidays(ctx, tenantID, from, to)
	if err != nil {
		return nil, fmt.Errorf("attendance: holidays: %w", err)
	}
	national := map[time.Time]bool{}
	byCounty := map[string][]time.Time{}
	for _, h := range rows {
		d := dateOnly(h.Date)
		if h.IsNational {
			national[d] = true
		} else if h.County != nil {
			byCounty[countyKey(*h.County)] = append(byCounty[countyKey(*h.County)], d)
		}
	}
	counties := map[uuid.UUID][]string{}
	if len(byCounty) > 0 {
		if counties, err = s.employeeCounties(ctx, tenantID, empIDs); err != nil {
			return nil, err
		}
	}
	return func(emp uuid.UUID, d time.Time) bool {
		return holidaysFor(national, byCounty, counties[emp])[d]
	}, nil
}

// monthlyHours is each employee's monthly hours basis: their standard shift's weekly hours
// times 52 over 12, else the tenant's standard_monthly_hours. It also returns their outlets.
func (s *Service) monthlyHours(ctx context.Context, tenantID uuid.UUID, empIDs []uuid.UUID, st Settings) (map[uuid.UUID]decimal.Decimal, map[uuid.UUID]*uuid.UUID, error) {
	emps, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(empIDs...)).
		Select(employee.FieldID, employee.FieldWorkShiftID, employee.FieldOutletID).All(ctx)
	if err != nil {
		return nil, nil, fmt.Errorf("attendance: employees: %w", err)
	}
	shiftIDs := []uuid.UUID{}
	for _, e := range emps {
		if e.WorkShiftID != nil {
			shiftIDs = append(shiftIDs, *e.WorkShiftID)
		}
	}
	weekly := map[uuid.UUID]decimal.Decimal{}
	if len(shiftIDs) > 0 {
		shifts, err := s.orm.WorkShift.Query().Where(workshift.TenantID(tenantID), workshift.IDIn(shiftIDs...)).All(ctx)
		if err != nil {
			return nil, nil, fmt.Errorf("attendance: shifts: %w", err)
		}
		for _, sh := range shifts {
			weekly[sh.ID] = sh.TotalHoursPerWeek
		}
	}
	basis := map[uuid.UUID]decimal.Decimal{}
	outlets := map[uuid.UUID]*uuid.UUID{}
	for _, e := range emps {
		basis[e.ID] = st.StandardMonthlyHours
		outlets[e.ID] = e.OutletID
		if e.WorkShiftID != nil && weekly[*e.WorkShiftID].IsPositive() {
			basis[e.ID] = weekly[*e.WorkShiftID].Mul(weeksPerMonth).Round(2)
		}
	}
	return basis, outlets, nil
}
