package attendance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerule"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
)

// evalInput is everything needed to derive a record's status and hours.
type evalInput struct {
	CheckIn  *time.Time
	CheckOut *time.Time
	WorkDate time.Time
	Shift    DayShift
	Loc      *time.Location
	Rule     *ent.AttendanceRule
	Settings Settings
}

// evalResult is the derived state written back to the record.
type evalResult struct {
	Status            string
	LateMinutes       int
	EarlyLeaveMinutes int
	Seconds           int
	Regular           decimal.Decimal
	Overtime          decimal.Decimal
}

// evaluate derives status, lateness, early leave and the regular/overtime split for one
// record. Pure, so the HTTP check-in, ESS clock-in and the device punch processor all share
// one set of rules.
func evaluate(in evalInput) evalResult {
	res := evalResult{Status: "present", Regular: decimal.Zero, Overtime: decimal.Zero}
	if in.CheckIn == nil {
		return res
	}
	res.LateMinutes = lateMinutesAt(*in.CheckIn, in.WorkDate, in.Shift.Start, in.Shift.Grace, in.Loc)
	if res.LateMinutes > 0 {
		res.Status = "late"
	}
	if in.CheckOut == nil || in.CheckOut.Before(*in.CheckIn) {
		return res
	}
	res.EarlyLeaveMinutes = earlyLeaveMinutes(*in.CheckOut, in.WorkDate, in.Shift.Start, in.Shift.End,
		in.Settings.EarlyLeaveGraceMinutes, in.Loc)
	res.Seconds = int(in.CheckOut.Sub(*in.CheckIn).Seconds())
	h := computeHours(computeHoursInput{
		TotalSecondsWorked: res.Seconds,
		HasCheckOut:        true,
		Rule:               in.Rule,
		Settings:           in.Settings,
		CurrentStatus:      res.Status,
	})
	res.Status, res.Regular, res.Overtime = h.Status, h.RegularHours, h.OvertimeHours
	return res
}

// ruleSet is the tenant's active overtime rules, picked per employee by scope.
type ruleSet struct {
	rules []*ent.AttendanceRule // priority desc
	dept  map[uuid.UUID]uuid.UUID
}

// loadRuleSet reads the active overtime rules and, when any rule is department-scoped, the
// departments of the given employees.
func (s *Service) loadRuleSet(ctx context.Context, tenantID uuid.UUID, empIDs []uuid.UUID) (*ruleSet, error) {
	rules, err := s.orm.AttendanceRule.Query().Where(
		attendancerule.TenantID(tenantID),
		attendancerule.IsActive(true),
		attendancerule.RuleTypeEQ(attendancerule.RuleTypeOvertimePolicy),
	).Order(ent.Desc(attendancerule.FieldPriority)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: overtime rules: %w", err)
	}
	rs := &ruleSet{rules: rules, dept: map[uuid.UUID]uuid.UUID{}}
	needDept := false
	for _, r := range rules {
		if r.DepartmentID != nil {
			needDept = true
		}
	}
	if needDept && len(empIDs) > 0 {
		rows, err := s.orm.HRDetails.Query().Where(hrdetails.TenantID(tenantID),
			hrdetails.EmployeeIDIn(empIDs...), hrdetails.DepartmentIDNotNil()).
			Select(hrdetails.FieldEmployeeID, hrdetails.FieldDepartmentID).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: rule departments: %w", err)
		}
		for _, d := range rows {
			rs.dept[d.EmployeeID] = *d.DepartmentID
		}
	}
	return rs, nil
}

// pick returns the most specific rule matching the employee (department and branch, then
// department, then branch, then tenant-wide), the higher priority first within a level.
func (rs *ruleSet) pick(emp uuid.UUID, outlet *uuid.UUID) *ent.AttendanceRule {
	if rs == nil {
		return nil
	}
	dept, hasDept := rs.dept[emp]
	var best *ent.AttendanceRule
	bestScore := -1
	for _, r := range rs.rules {
		score := 0
		if r.DepartmentID != nil {
			if !hasDept || *r.DepartmentID != dept {
				continue
			}
			score += 2
		}
		if r.BranchID != nil {
			if outlet == nil || *r.BranchID != *outlet {
				continue
			}
			score++
		}
		if score > bestScore {
			best, bestScore = r, score
		}
	}
	return best
}
