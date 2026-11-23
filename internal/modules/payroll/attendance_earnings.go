package payroll

import (
	"context"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// EarningLine is one extra cash earning on a payslip.
type EarningLine struct {
	Code   string
	Label  string
	Amount decimal.Decimal
}

// runEarnings is the period's overtime, holiday and piece pay inputs, loaded once per run.
type runEarnings struct {
	time   map[uuid.UUID]attendance.PayableTime
	pieces map[uuid.UUID][]*ent.PieceOutput
	units  map[uuid.UUID]string // piece rate id -> name, for labels
}

// loadAttendanceEarnings reads payable overtime and holiday time (only when the tenant pays
// overtime through payroll) and the month's approved piece output.
func (s *Service) loadAttendanceEarnings(ctx context.Context, p RunParams, emps []*ent.Employee) (*runEarnings, error) {
	ids := make([]uuid.UUID, len(emps))
	for i, e := range emps {
		ids[i] = e.ID
	}
	re := &runEarnings{units: map[uuid.UUID]string{}}
	var err error
	if re.time, err = attendance.PayableTimeForPeriod(ctx, s.orm, p.TenantID, p.Period, ids); err != nil {
		return nil, err
	}
	if re.pieces, err = s.approvedPieceOutputs(ctx, p.TenantID, p.Period); err != nil {
		return nil, fmt.Errorf("piece output: %w", err)
	}
	if rates, err := s.ListPieceRates(ctx, p.TenantID, false); err == nil {
		for _, r := range rates {
			re.units[r.ID] = r.Name
		}
	}
	return re, nil
}

// apply adds an employee's earnings to the engine input (taxable cash, so PAYE and statutory
// deductions see them) and to the itemised payslip lines.
func (re *runEarnings) apply(emp uuid.UUID, in *payrollengine.EmployeeInput, items *EmployeeItemized) {
	if re == nil {
		return
	}
	add := func(code, label string, amt decimal.Decimal) {
		if !amt.IsPositive() {
			return
		}
		in.TaxableAllowances = in.TaxableAllowances.Add(amt)
		items.Earnings = append(items.Earnings, EarningLine{Code: code, Label: label, Amount: amt})
	}
	if pt, ok := re.time[emp]; ok {
		ot, hol := pt.Amount(in.GrossPay)
		add("overtime", fmt.Sprintf("Overtime (%s h x %s)", pt.OvertimeHours.Round(2), pt.OvertimeMultiplier.Round(2)), ot)
		add("holiday_pay", fmt.Sprintf("Holiday work (%s h x %s)", pt.HolidayHours.Round(2), pt.HolidayMultiplier.Round(2)), hol)
	}
	byRate := map[uuid.UUID]decimal.Decimal{}
	order := []uuid.UUID{}
	for _, o := range re.pieces[emp] {
		if _, seen := byRate[o.PieceRateID]; !seen {
			order = append(order, o.PieceRateID)
		}
		byRate[o.PieceRateID] = byRate[o.PieceRateID].Add(o.Amount)
		items.PieceOutputIDs = append(items.PieceOutputIDs, o.ID)
	}
	for _, id := range order {
		name := strings.TrimSpace(re.units[id])
		if name == "" {
			name = "output"
		}
		add("piece_work", "Piece work: "+name, byRate[id])
	}
}
