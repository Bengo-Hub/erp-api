package payroll

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancededuction"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerule"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// Attendance deductions turn a month's lateness and unexcused absence into reviewable pay
// deductions (AttendanceDeduction rows). Nothing reaches a payslip until HR approves a row.
//
// Pricing, per employee and month:
//   - Daily rate = monthly salary / weekdays (Monday to Friday) in the month. Minute rate =
//     daily rate / standard hours (the work-hours policy, default 8) / 60.
//   - Late: the most specific active late policy (department, then branch, then tenant-wide,
//     highest priority first). An arrival counts when it is more than late_threshold_minutes
//     after the shift start (records marked late without a shift always count). By
//     late_penalty_type: "warning" deducts nothing; "fixed" = value per late arrival;
//     "percent_daily" (or "percentage") = value % of the daily rate per late arrival;
//     "per_minute" (or "deduct_minutes") = minutes late x minute rate (x value when above 0).
//   - Absence: days marked absent that no approved leave covers, at the daily rate. An active
//     absenteeism policy whose action is not a deduction ("warning", the default) turns it off.

// Absenteeism actions that mean "deduct the absent days".
var deductingAbsenceActions = map[string]bool{"deduct": true, "deduction": true, "salary_deduction": true, "unpaid": true}

// AttendanceDeductionModel is a deduction row for the review screen.
type AttendanceDeductionModel struct {
	ID           uuid.UUID       `json:"id"`
	EmployeeID   uuid.UUID       `json:"employee_id"`
	EmployeeName string          `json:"employee_name"`
	Period       string          `json:"period"` // YYYY-MM
	Kind         string          `json:"kind"`
	Occurrences  int             `json:"occurrences"`
	Minutes      int             `json:"minutes"`
	Amount       decimal.Decimal `json:"amount"`
	Basis        string          `json:"basis"`
	Status       string          `json:"status"`
	ReviewedBy   *uuid.UUID      `json:"reviewed_by,omitempty"`
	ReviewedAt   *time.Time      `json:"reviewed_at,omitempty"`
	Note         string          `json:"note,omitempty"`
	PayslipID    *uuid.UUID      `json:"payslip_id,omitempty"`
}

// ComputeSummary reports what a recompute changed.
type ComputeSummary struct {
	Period   string `json:"period"`
	Created  int    `json:"created"`
	Updated  int    `json:"updated"`
	Removed  int    `json:"removed"`
	Reviewed int    `json:"reviewed_kept"` // approved, waived or applied rows left untouched
}

// ErrDeductionState is returned when a review action does not fit a row's status.
var ErrDeductionState = errors.New("attendance deduction: action not allowed in this status")

// penaltyRule is the part of an AttendanceRule the pricing reads.
type penaltyRule struct {
	ID        *uuid.UUID
	Type      string
	Value     decimal.Decimal
	Threshold int
}

type computedDeduction struct {
	Kind        attendancededuction.Kind
	Occurrences int
	Minutes     int
	Amount      decimal.Decimal
	Basis       string
	RuleID      *uuid.UUID
}

// weekdaysIn counts Monday to Friday in the month.
func weekdaysIn(month time.Time) int {
	n := 0
	for d := month; d.Month() == month.Month(); d = d.AddDate(0, 0, 1) {
		if wd := d.Weekday(); wd != time.Saturday && wd != time.Sunday {
			n++
		}
	}
	return n
}

// dailyRate is the monthly salary spread over the month's weekdays.
func dailyRate(monthly decimal.Decimal, month time.Time) decimal.Decimal {
	days := weekdaysIn(month)
	if days == 0 || !monthly.IsPositive() {
		return decimal.Zero
	}
	return monthly.Div(decimal.NewFromInt(int64(days)))
}

// priceLate prices a month's late arrivals (minutes per arrival; -1 means late with no shift to
// measure against). ok=false means the rule deducts nothing.
func priceLate(rule penaltyRule, daily, stdHours decimal.Decimal, arrivals []int) (computedDeduction, bool) {
	out := computedDeduction{Kind: attendancededuction.KindLate, RuleID: rule.ID}
	for _, m := range arrivals {
		if m >= 0 && m <= rule.Threshold {
			continue
		}
		out.Occurrences++
		if m > 0 {
			out.Minutes += m
		}
	}
	if out.Occurrences == 0 {
		return out, false
	}
	occ := decimal.NewFromInt(int64(out.Occurrences))
	switch strings.ToLower(strings.TrimSpace(rule.Type)) {
	case "fixed":
		out.Amount = rule.Value.Mul(occ)
		out.Basis = fmt.Sprintf("%d late arrivals x %s", out.Occurrences, rule.Value.StringFixed(2))
	case "percent_daily", "percentage", "percent":
		out.Amount = daily.Mul(rule.Value).Div(decimal.NewFromInt(100)).Mul(occ)
		out.Basis = fmt.Sprintf("%d late arrivals x %s%% of the daily rate %s", out.Occurrences, rule.Value.String(), daily.StringFixed(2))
	case "per_minute", "deduct_minutes", "salary_deduction":
		if out.Minutes == 0 || !stdHours.IsPositive() {
			return out, false
		}
		perMinute := daily.Div(stdHours).Div(decimal.NewFromInt(60))
		mult := decimal.NewFromInt(1)
		if rule.Value.IsPositive() {
			mult = rule.Value
		}
		out.Amount = perMinute.Mul(decimal.NewFromInt(int64(out.Minutes))).Mul(mult)
		out.Basis = fmt.Sprintf("%d minutes late over %d arrivals at %s a minute", out.Minutes, out.Occurrences, perMinute.StringFixed(2))
		if mult.GreaterThan(decimal.NewFromInt(1)) {
			out.Basis += fmt.Sprintf(" x %s", mult.String())
		}
	default: // "warning" or anything unknown: record nothing
		return out, false
	}
	out.Amount = out.Amount.Round(2)
	return out, out.Amount.IsPositive()
}

// priceAbsence prices unexcused absent days at the daily rate.
func priceAbsence(daily decimal.Decimal, days int, ruleID *uuid.UUID) (computedDeduction, bool) {
	out := computedDeduction{Kind: attendancededuction.KindAbsence, Occurrences: days, RuleID: ruleID}
	if days == 0 || !daily.IsPositive() {
		return out, false
	}
	out.Amount = daily.Mul(decimal.NewFromInt(int64(days))).Round(2)
	out.Basis = fmt.Sprintf("%d unexcused absent days x daily rate %s", days, daily.StringFixed(2))
	return out, true
}

// pickRule returns the most specific active rule for an employee: department, then branch
// (outlet), then tenant-wide; the highest priority within a level.
func pickRule(rules []*ent.AttendanceRule, dept, outlet *uuid.UUID) *ent.AttendanceRule {
	var best *ent.AttendanceRule
	bestLevel := -1
	for _, r := range rules {
		level := 0
		switch {
		case r.DepartmentID != nil:
			if dept == nil || *r.DepartmentID != *dept {
				continue
			}
			level = 2
		case r.BranchID != nil:
			if outlet == nil || *r.BranchID != *outlet {
				continue
			}
			level = 1
		}
		if level > bestLevel || (level == bestLevel && r.Priority > best.Priority) {
			best, bestLevel = r, level
		}
	}
	return best
}

// ComputeAttendanceDeductions rebuilds the month's pending deductions from attendance. Rows
// already approved, waived or applied are never changed; a pending row whose basis disappeared
// (attendance corrected, leave approved) is removed. One pass of batched reads, one transaction.
func (s *Service) ComputeAttendanceDeductions(ctx context.Context, tenantID uuid.UUID, month time.Time) (ComputeSummary, error) {
	month = time.Date(month.Year(), month.Month(), 1, 0, 0, 0, 0, time.UTC)
	next := month.AddDate(0, 1, 0)
	sum := ComputeSummary{Period: month.Format("2006-01")}

	records, err := s.orm.AttendanceRecord.Query().Where(
		attendancerecord.TenantID(tenantID),
		attendancerecord.DateGTE(month), attendancerecord.DateLT(next),
		attendancerecord.StatusIn(attendancerecord.StatusLate, attendancerecord.StatusAbsent),
	).All(ctx)
	if err != nil {
		return sum, err
	}
	empIDs := map[uuid.UUID]bool{}
	for _, r := range records {
		empIDs[r.EmployeeID] = true
	}
	computed := map[uuid.UUID][]computedDeduction{}
	if len(empIDs) > 0 {
		if computed, err = s.priceMonth(ctx, tenantID, month, next, records, keys(empIDs)); err != nil {
			return sum, err
		}
	}

	existing, err := s.orm.AttendanceDeduction.Query().Where(
		attendancededuction.TenantID(tenantID), attendancededuction.Period(month),
	).All(ctx)
	if err != nil {
		return sum, err
	}
	type key struct {
		emp  uuid.UUID
		kind attendancededuction.Kind
	}
	have := make(map[key]*ent.AttendanceDeduction, len(existing))
	for _, e := range existing {
		have[key{e.EmployeeID, e.Kind}] = e
	}

	err = withTx(ctx, s.orm, func(tx *ent.Tx) error {
		var creates []*ent.AttendanceDeductionCreate
		seen := map[key]bool{}
		for emp, rows := range computed {
			for _, c := range rows {
				k := key{emp, c.Kind}
				seen[k] = true
				cur := have[k]
				switch {
				case cur == nil:
					creates = append(creates, tx.AttendanceDeduction.Create().
						SetTenantID(tenantID).SetEmployeeID(emp).SetPeriod(month).SetKind(c.Kind).
						SetOccurrences(c.Occurrences).SetMinutes(c.Minutes).SetAmount(c.Amount).
						SetBasis(c.Basis).SetNillableRuleID(c.RuleID))
					sum.Created++
				case cur.Status == attendancededuction.StatusPending:
					if err := tx.AttendanceDeduction.UpdateOneID(cur.ID).
						SetOccurrences(c.Occurrences).SetMinutes(c.Minutes).SetAmount(c.Amount).
						SetBasis(c.Basis).SetNillableRuleID(c.RuleID).Exec(ctx); err != nil {
						return err
					}
					sum.Updated++
				default:
					sum.Reviewed++
				}
			}
		}
		for k, cur := range have {
			if seen[k] {
				continue
			}
			if cur.Status != attendancededuction.StatusPending {
				sum.Reviewed++
				continue
			}
			if err := tx.AttendanceDeduction.DeleteOneID(cur.ID).Exec(ctx); err != nil {
				return err
			}
			sum.Removed++
		}
		for i := 0; i < len(creates); i += 500 {
			end := min(i+500, len(creates))
			if err := tx.AttendanceDeduction.CreateBulk(creates[i:end]...).Exec(ctx); err != nil {
				return err
			}
		}
		return nil
	})
	return sum, err
}

// priceMonth loads everything the pricing needs for the month's employees in a fixed number of
// queries and returns the deductions that come to more than zero.
func (s *Service) priceMonth(ctx context.Context, tenantID uuid.UUID, month, next time.Time, records []*ent.AttendanceRecord, emps []uuid.UUID) (map[uuid.UUID][]computedDeduction, error) {
	out := map[uuid.UUID][]computedDeduction{}
	rules, err := s.orm.AttendanceRule.Query().Where(
		attendancerule.TenantID(tenantID), attendancerule.IsActive(true),
		attendancerule.RuleTypeIn(attendancerule.RuleTypeLatePolicy, attendancerule.RuleTypeAbsenteeismPolicy, attendancerule.RuleTypeWorkHoursPolicy),
	).All(ctx)
	if err != nil {
		return nil, err
	}
	var lateRules, absRules, hourRules []*ent.AttendanceRule
	for _, r := range rules {
		switch r.RuleType {
		case attendancerule.RuleTypeLatePolicy:
			lateRules = append(lateRules, r)
		case attendancerule.RuleTypeAbsenteeismPolicy:
			absRules = append(absRules, r)
		case attendancerule.RuleTypeWorkHoursPolicy:
			hourRules = append(hourRules, r)
		}
	}

	salaries := map[uuid.UUID]decimal.Decimal{}
	depts := map[uuid.UUID]*uuid.UUID{}
	outlets := map[uuid.UUID]*uuid.UUID{}
	covered := map[uuid.UUID][]*ent.LeaveRequest{}
	for i := 0; i < len(emps); i += 1000 {
		chunk := emps[i:min(i+1000, len(emps))]
		sal, err := s.orm.SalaryDetails.Query().Where(
			salarydetails.TenantID(tenantID), salarydetails.EmployeeIDIn(chunk...), salarydetails.IsActive(true),
		).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, sd := range sal {
			if _, ok := salaries[sd.EmployeeID]; !ok {
				salaries[sd.EmployeeID] = sd.MonthlySalary
			}
		}
		hr, err := s.orm.HRDetails.Query().Where(hrdetails.TenantID(tenantID), hrdetails.EmployeeIDIn(chunk...)).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, h := range hr {
			depts[h.EmployeeID] = h.DepartmentID
		}
		es, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(chunk...)).
			Select(employee.FieldID, employee.FieldOutletID).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, e := range es {
			outlets[e.ID] = e.OutletID
		}
		leaves, err := s.orm.LeaveRequest.Query().Where(
			leaverequest.TenantID(tenantID), leaverequest.EmployeeIDIn(chunk...),
			leaverequest.StatusEQ(leaverequest.StatusApproved),
			leaverequest.StartDateLT(next), leaverequest.EndDateGTE(month),
		).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, l := range leaves {
			covered[l.EmployeeID] = append(covered[l.EmployeeID], l)
		}
	}

	var lateRecs []*ent.AttendanceRecord
	for _, r := range records {
		if r.Status == attendancerecord.StatusLate {
			lateRecs = append(lateRecs, r)
		}
	}
	lateMin, err := attendance.LateMinutes(ctx, s.orm, tenantID, lateRecs)
	if err != nil {
		return nil, err
	}

	arrivals := map[uuid.UUID][]int{}
	absentDays := map[uuid.UUID]map[string]bool{}
	for _, r := range records {
		switch r.Status {
		case attendancerecord.StatusLate:
			m, ok := lateMin[r.ID]
			if !ok {
				m = -1 // late, but no shift to measure against
				if r.WorkShiftID != nil && r.CheckIn != nil {
					m = 0 // measured: on time or within grace after all
				}
			}
			arrivals[r.EmployeeID] = append(arrivals[r.EmployeeID], m)
		case attendancerecord.StatusAbsent:
			if onLeave(covered[r.EmployeeID], r.Date) {
				continue
			}
			if absentDays[r.EmployeeID] == nil {
				absentDays[r.EmployeeID] = map[string]bool{}
			}
			absentDays[r.EmployeeID][r.Date.Format("2006-01-02")] = true
		}
	}

	for _, emp := range emps {
		monthly, ok := salaries[emp]
		if !ok {
			continue // no active salary: nothing to deduct from
		}
		daily := dailyRate(monthly, month)
		stdHours := decimal.NewFromInt(8)
		if hr := pickRule(hourRules, depts[emp], outlets[emp]); hr != nil && hr.StandardWorkHours.IsPositive() {
			stdHours = hr.StandardWorkHours
		}
		if rule := pickRule(lateRules, depts[emp], outlets[emp]); rule != nil && len(arrivals[emp]) > 0 {
			id := rule.ID
			if c, ok := priceLate(penaltyRule{ID: &id, Type: rule.LatePenaltyType, Value: rule.LatePenaltyValue, Threshold: rule.LateThresholdMinutes}, daily, stdHours, arrivals[emp]); ok {
				out[emp] = append(out[emp], c)
			}
		}
		if days := len(absentDays[emp]); days > 0 {
			var ruleID *uuid.UUID
			if rule := pickRule(absRules, depts[emp], outlets[emp]); rule != nil {
				if !deductingAbsenceActions[strings.ToLower(strings.TrimSpace(rule.AbsenteeismAction))] {
					continue
				}
				id := rule.ID
				ruleID = &id
			}
			if c, ok := priceAbsence(daily, days, ruleID); ok {
				out[emp] = append(out[emp], c)
			}
		}
	}
	return out, nil
}

func onLeave(leaves []*ent.LeaveRequest, day time.Time) bool {
	d := day.Format("2006-01-02")
	for _, l := range leaves {
		if d >= l.StartDate.Format("2006-01-02") && d <= l.EndDate.Format("2006-01-02") {
			return true
		}
	}
	return false
}

func keys(m map[uuid.UUID]bool) []uuid.UUID {
	out := make([]uuid.UUID, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].String() < out[j].String() })
	return out
}

// AttendanceDeductionFilter narrows the review list.
type AttendanceDeductionFilter struct {
	Month      time.Time
	Status     string
	EmployeeID *uuid.UUID
	Limit      int
	Offset     int
}

// ListAttendanceDeductions pages a month's deductions, largest first, with employee names.
func (s *Service) ListAttendanceDeductions(ctx context.Context, tenantID uuid.UUID, f AttendanceDeductionFilter) ([]AttendanceDeductionModel, int, decimal.Decimal, error) {
	month := time.Date(f.Month.Year(), f.Month.Month(), 1, 0, 0, 0, 0, time.UTC)
	q := s.orm.AttendanceDeduction.Query().Where(attendancededuction.TenantID(tenantID), attendancededuction.Period(month))
	if f.Status != "" {
		q = q.Where(attendancededuction.StatusEQ(attendancededuction.Status(f.Status)))
	}
	if f.EmployeeID != nil {
		q = q.Where(attendancededuction.EmployeeID(*f.EmployeeID))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, decimal.Zero, err
	}
	var agg []struct {
		Sum decimal.NullDecimal `json:"sum"`
	}
	if err := q.Clone().Aggregate(ent.Sum(attendancededuction.FieldAmount)).Scan(ctx, &agg); err != nil {
		return nil, 0, decimal.Zero, err
	}
	amount := decimal.Zero
	if len(agg) > 0 && agg[0].Sum.Valid {
		amount = agg[0].Sum.Decimal
	}
	if f.Limit <= 0 || f.Limit > 200 {
		f.Limit = 50
	}
	rows, err := q.Order(ent.Desc(attendancededuction.FieldAmount), ent.Asc(attendancededuction.FieldID)).
		Offset(f.Offset).Limit(f.Limit).All(ctx)
	if err != nil {
		return nil, 0, decimal.Zero, err
	}
	ids := make([]uuid.UUID, 0, len(rows))
	for _, r := range rows {
		ids = append(ids, r.EmployeeID)
	}
	names := map[uuid.UUID]string{}
	if len(ids) > 0 {
		es, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(ids...)).All(ctx)
		if err != nil {
			return nil, 0, decimal.Zero, err
		}
		for _, e := range es {
			names[e.ID] = employeeDisplayName(e)
		}
	}
	out := make([]AttendanceDeductionModel, 0, len(rows))
	for _, r := range rows {
		m := AttendanceDeductionModel{
			ID: r.ID, EmployeeID: r.EmployeeID, EmployeeName: names[r.EmployeeID], Period: r.Period.Format("2006-01"),
			Kind: string(r.Kind), Occurrences: r.Occurrences, Minutes: r.Minutes, Amount: r.Amount, Basis: r.Basis,
			Status: string(r.Status), ReviewedBy: r.ReviewedBy, ReviewedAt: r.ReviewedAt, PayslipID: r.PayslipID,
		}
		if r.Note != nil {
			m.Note = *r.Note
		}
		out = append(out, m)
	}
	return out, total, amount, nil
}

// ReviewAttendanceDeductions approves, waives or reopens rows. Approve and waive act on pending
// rows; reopen returns approved or waived rows to pending. Applied rows never change. It returns
// how many rows changed; rows in another status are skipped.
func (s *Service) ReviewAttendanceDeductions(ctx context.Context, tenantID, reviewer uuid.UUID, ids []uuid.UUID, action, note string) (int, error) {
	if len(ids) == 0 {
		return 0, nil
	}
	if len(ids) > 1000 {
		return 0, fmt.Errorf("%w: at most 1000 rows per request", ErrDeductionState)
	}
	now := time.Now().UTC()
	u := s.orm.AttendanceDeduction.Update().Where(attendancededuction.TenantID(tenantID), attendancededuction.IDIn(ids...))
	switch action {
	case "approve":
		u = u.Where(attendancededuction.StatusEQ(attendancededuction.StatusPending)).
			SetStatus(attendancededuction.StatusApproved).SetReviewedBy(reviewer).SetReviewedAt(now)
	case "waive":
		u = u.Where(attendancededuction.StatusEQ(attendancededuction.StatusPending)).
			SetStatus(attendancededuction.StatusWaived).SetReviewedBy(reviewer).SetReviewedAt(now)
	case "reopen":
		u = u.Where(attendancededuction.StatusIn(attendancededuction.StatusApproved, attendancededuction.StatusWaived)).
			SetStatus(attendancededuction.StatusPending).ClearReviewedBy().ClearReviewedAt()
	default:
		return 0, fmt.Errorf("%w: unknown action %q", ErrDeductionState, action)
	}
	if note = strings.TrimSpace(note); note != "" {
		u = u.SetNote(note)
	}
	return u.Save(ctx)
}

// approvedAttendanceDeductions returns the month's approved (or already applied) deductions per
// employee, for the payroll run. One query for the whole run.
func (s *Service) approvedAttendanceDeductions(ctx context.Context, tenantID uuid.UUID, period time.Time) (map[uuid.UUID][]*ent.AttendanceDeduction, error) {
	month := time.Date(period.Year(), period.Month(), 1, 0, 0, 0, 0, time.UTC)
	rows, err := s.orm.AttendanceDeduction.Query().Where(
		attendancededuction.TenantID(tenantID), attendancededuction.Period(month),
		attendancededuction.StatusIn(attendancededuction.StatusApproved, attendancededuction.StatusApplied),
	).All(ctx)
	if err != nil {
		return nil, err
	}
	out := map[uuid.UUID][]*ent.AttendanceDeduction{}
	for _, r := range rows {
		out[r.EmployeeID] = append(out[r.EmployeeID], r)
	}
	return out, nil
}

func withTx(ctx context.Context, orm *ent.Client, fn func(tx *ent.Tx) error) error {
	tx, err := orm.Tx(ctx)
	if err != nil {
		return err
	}
	if err := fn(tx); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}

func employeeDisplayName(e *ent.Employee) string {
	return strings.TrimSpace(e.FirstName + " " + e.LastName)
}

// markAttendanceApplied records that the deductions went into a payslip. Rows already applied
// to an earlier version of the same payslip are re-pointed at it (a re-run replaces payslips).
func (s *Service) markAttendanceApplied(ctx context.Context, tenantID, payslipID uuid.UUID, ids []uuid.UUID) error {
	if len(ids) == 0 {
		return nil
	}
	return s.orm.AttendanceDeduction.Update().
		Where(attendancededuction.TenantID(tenantID), attendancededuction.IDIn(ids...),
			attendancededuction.StatusIn(attendancededuction.StatusApproved, attendancededuction.StatusApplied)).
		SetStatus(attendancededuction.StatusApplied).SetPayslipID(payslipID).
		Exec(ctx)
}

// attendanceLabel is the payslip line label for a deduction.
func attendanceLabel(d *ent.AttendanceDeduction) string {
	if d.Kind == attendancededuction.KindAbsence {
		return fmt.Sprintf("Unpaid absence (%d days)", d.Occurrences)
	}
	return fmt.Sprintf("Late arrival deduction (%d)", d.Occurrences)
}
