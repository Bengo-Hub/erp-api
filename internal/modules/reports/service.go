// Package reports implements the ERP reporting layer powering the erp-ui report-runner:
// Kenyan statutory payroll returns (P9, P10A, NHIF/SHIF, NSSF, NITA, withholding tax),
// bank net-pay schedule, and headcount/leave/payroll summaries. Every report aggregates
// HRM/payroll data already owned by the ERP and is strictly tenant-scoped. Reports are
// read-only and return structured JSON the UI renders / exports.
package reports

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
)

// Service aggregates HRM/payroll data into reports. Tenant-scoped; never crosses services.
type Service struct {
	orm *ent.Client
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// Period is the inclusive [Start, End) window a report covers. Filter narrows by outlet.
type Filter struct {
	Start    time.Time
	End      time.Time
	OutletID *uuid.UUID
}

// ResolvePeriod builds a Filter from year + optional month (1-12). month=0 => full year.
func ResolvePeriod(year, month int, outletID *uuid.UUID) (Filter, error) {
	if year < 2000 || year > 3000 {
		return Filter{}, fmt.Errorf("reports: invalid year %d", year)
	}
	if month < 0 || month > 12 {
		return Filter{}, fmt.Errorf("reports: invalid month %d", month)
	}
	var start, end time.Time
	if month == 0 {
		start = time.Date(year, 1, 1, 0, 0, 0, 0, time.UTC)
		end = start.AddDate(1, 0, 0)
	} else {
		start = time.Date(year, time.Month(month), 1, 0, 0, 0, 0, time.UTC)
		end = start.AddDate(0, 1, 0)
	}
	return Filter{Start: start, End: end, OutletID: outletID}, nil
}

// fetchPayslips returns the tenant's payslips within the period (active rows only).
func (s *Service) fetchPayslips(ctx context.Context, tenantID uuid.UUID, f Filter) ([]*ent.Payslip, error) {
	q := s.orm.Payslip.Query().
		Where(
			payslip.TenantID(tenantID),
			payslip.DeleteStatus(false),
			payslip.PaymentPeriodGTE(f.Start),
			payslip.PaymentPeriodLT(f.End),
		)
	if f.OutletID != nil {
		q = q.Where(payslip.OutletID(*f.OutletID))
	}
	return q.Order(ent.Asc(payslip.FieldEmployeeID)).All(ctx)
}

// employeeMap returns a tenant-scoped employee lookup keyed by id (for names/PIN on reports).
func (s *Service) employeeMap(ctx context.Context, tenantID uuid.UUID) (map[uuid.UUID]*ent.Employee, error) {
	rows, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("reports: load employees: %w", err)
	}
	m := make(map[uuid.UUID]*ent.Employee, len(rows))
	for _, e := range rows {
		m[e.ID] = e
	}
	return m, nil
}

// empName composes "First Last" with a sensible fallback.
func empName(e *ent.Employee) string {
	if e == nil {
		return ""
	}
	name := e.FirstName
	if e.LastName != "" {
		if name != "" {
			name += " "
		}
		name += e.LastName
	}
	return name
}

// d is a decimal helper for zero-safe sums.
func d() decimal.Decimal { return decimal.Zero }
