package contracts

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
)

// The contract's salary is the figure agreed on that document and is never rewritten. What the
// person is paid is the active salary_details row (the one a payroll run reads); this file only
// reads it, so a contract can say whether it still states the current pay.

// CurrentSalaries returns each employee's current monthly salary (the newest active row). An
// employee without one is absent.
func (s *Service) CurrentSalaries(ctx context.Context, tenantID uuid.UUID, employeeIDs []uuid.UUID) (map[uuid.UUID]decimal.Decimal, error) {
	out := map[uuid.UUID]decimal.Decimal{}
	if len(employeeIDs) == 0 {
		return out, nil
	}
	rows, err := s.orm.SalaryDetails.Query().
		Where(salarydetails.TenantID(tenantID), salarydetails.EmployeeIDIn(employeeIDs...), salarydetails.IsActive(true)).
		Order(ent.Asc(salarydetails.FieldCreatedAt)).All(ctx)
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		out[r.EmployeeID] = r.MonthlySalary
	}
	return out, nil
}

// InForce reports whether the contract is active on the day.
func InForce(c *ent.Contract, day time.Time) bool {
	if c.Status != "active" || (c.StartDate != nil && day.Before(*c.StartDate)) {
		return false
	}
	return c.EndDate == nil || !day.After(c.EndDate.AddDate(0, 0, 1).Add(-time.Nanosecond))
}
