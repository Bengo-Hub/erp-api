package reports

import (
	"context"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
)

// HeadcountSummary aggregates the active employee population by status.
func (s *Service) HeadcountSummary(ctx context.Context, tenantID uuid.UUID, outletID *uuid.UUID) (*Report, error) {
	q := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.Deleted(false))
	if outletID != nil {
		q = q.Where(employee.OutletID(*outletID))
	}
	// Counted in SQL (one row per status), not by loading every employee.
	var counts []struct {
		Terminated bool `json:"terminated"`
		Count      int  `json:"count"`
	}
	if err := q.GroupBy(employee.FieldTerminated).Aggregate(entCount()).Scan(ctx, &counts); err != nil {
		return nil, err
	}
	active, terminated := 0, 0
	for _, c := range counts {
		if c.Terminated {
			terminated = c.Count
		} else {
			active = c.Count
		}
	}
	total := active + terminated
	return &Report{
		Report:  "headcount_summary",
		Columns: []string{"metric", "value"},
		Rows: []map[string]any{
			{"metric": "total", "value": total},
			{"metric": "active", "value": active},
			{"metric": "terminated", "value": terminated},
		},
		Totals: map[string]any{"total": total, "active": active, "terminated": terminated},
	}, nil
}

// LeaveSummary aggregates leave balances + pending requests for a year.
func (s *Service) LeaveSummary(ctx context.Context, tenantID uuid.UUID, year int) (*Report, error) {
	bals, err := s.orm.LeaveBalance.Query().
		Where(leavebalance.TenantID(tenantID), leavebalance.Year(year)).All(ctx)
	if err != nil {
		return nil, err
	}
	pending, err := s.orm.LeaveRequest.Query().
		Where(leaverequest.TenantID(tenantID), leaverequest.StatusEQ(leaverequest.StatusPending)).Count(ctx)
	if err != nil {
		return nil, err
	}
	entitled, taken, remaining := d(), d(), d()
	for _, b := range bals {
		entitled = entitled.Add(b.DaysEntitled)
		taken = taken.Add(b.DaysTaken)
		remaining = remaining.Add(b.DaysRemaining)
	}
	return &Report{
		Report:  "leave_summary",
		Columns: []string{"metric", "value"},
		Rows: []map[string]any{
			{"metric": "days_entitled", "value": entitled.StringFixed(2)},
			{"metric": "days_taken", "value": taken.StringFixed(2)},
			{"metric": "days_remaining", "value": remaining.StringFixed(2)},
			{"metric": "pending_requests", "value": pending},
		},
		Totals: map[string]any{
			"days_entitled": entitled.StringFixed(2), "days_taken": taken.StringFixed(2),
			"days_remaining": remaining.StringFixed(2), "pending_requests": pending,
		},
	}, nil
}

// PayrollSummary totals the period's payroll (gross, statutory, net) across all payslips.
func (s *Service) PayrollSummary(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	gross, paye, shif, nssfE, nssfR, house, net := d(), d(), d(), d(), d(), d(), d()
	for _, p := range slips {
		gross = gross.Add(p.GrossPay)
		paye = paye.Add(p.Paye)
		shif = shif.Add(p.ShifOrNhifContribution)
		nssfE = nssfE.Add(p.NssfEmployeeTier1).Add(p.NssfEmployeeTier2)
		nssfR = nssfR.Add(p.NssfEmployerContribution)
		house = house.Add(p.HousingLevy)
		net = net.Add(p.NetPay)
	}
	return &Report{
		Report:  "payroll_summary",
		Period:  periodMeta(f),
		Columns: []string{"metric", "value"},
		Rows: []map[string]any{
			{"metric": "payslips", "value": len(slips)},
			{"metric": "gross_pay", "value": money(gross)},
			{"metric": "paye", "value": money(paye)},
			{"metric": "shif_nhif", "value": money(shif)},
			{"metric": "nssf_employee", "value": money(nssfE)},
			{"metric": "nssf_employer", "value": money(nssfR)},
			{"metric": "housing_levy", "value": money(house)},
			{"metric": "net_pay", "value": money(net)},
		},
		Totals: map[string]any{
			"payslips": len(slips), "gross_pay": money(gross), "paye": money(paye),
			"shif_nhif": money(shif), "nssf_employee": money(nssfE), "nssf_employer": money(nssfR),
			"housing_levy": money(house), "net_pay": money(net),
		},
	}, nil
}
