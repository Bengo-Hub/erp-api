package payroll

import (
	"context"
	"sort"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/department"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeprojectallocation"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
)

// Payroll cost attribution. Treasury books payroll as one salary expense; to let project and
// department budgets see their labour cost, the erp.payroll.processed event carries
// "allocations": each employee's gross pay split across their project allocations, with the
// rest attributed to the employee's department cost center. Treasury posts one salary line per
// allocation (the liability lines stay whole, so the journal balances).

// allocRule is one EmployeeProjectAllocation in force for the period.
type allocRule struct {
	ProjectID    uuid.UUID
	CostCenterID *uuid.UUID
	Percent      decimal.Decimal // 0-100
	Fixed        *decimal.Decimal
}

// costShare is gross pay attributed to one (project, cost center) pair. A nil ProjectID is
// unallocated cost (departmental overhead).
type costShare struct {
	ProjectID    *uuid.UUID
	CostCenterID *uuid.UUID
	Amount       decimal.Decimal
}

var hundred = decimal.NewFromInt(100)

// splitGross divides one employee's gross pay. Fixed amounts are taken first, then percentages
// of gross; the total never exceeds gross (later rules are trimmed to what is left), and whatever
// remains goes to the department's cost center with no project. Shares always add up to gross
// exactly, so the posted salary lines equal the payroll total.
func splitGross(gross decimal.Decimal, rules []allocRule, deptCC *uuid.UUID) []costShare {
	if !gross.IsPositive() {
		return nil
	}
	ordered := append([]allocRule(nil), rules...)
	sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].Fixed != nil && ordered[j].Fixed == nil })
	left := gross
	out := []costShare{}
	for _, r := range ordered {
		if !left.IsPositive() {
			break
		}
		amt := decimal.Zero
		if r.Fixed != nil {
			amt = *r.Fixed
		} else {
			amt = gross.Mul(r.Percent).Div(hundred).Round(2)
		}
		if !amt.IsPositive() {
			continue
		}
		if amt.GreaterThan(left) {
			amt = left
		}
		pid := r.ProjectID
		cc := r.CostCenterID
		if cc == nil {
			cc = deptCC
		}
		out = append(out, costShare{ProjectID: &pid, CostCenterID: cc, Amount: amt})
		left = left.Sub(amt)
	}
	if left.IsPositive() {
		out = append(out, costShare{CostCenterID: deptCC, Amount: left})
	}
	return out
}

// mergeShares sums shares with the same (project, cost center), in a stable order.
func mergeShares(shares []costShare) []costShare {
	type key struct{ p, c uuid.UUID }
	idx := map[key]int{}
	out := []costShare{}
	for _, s := range shares {
		k := key{}
		if s.ProjectID != nil {
			k.p = *s.ProjectID
		}
		if s.CostCenterID != nil {
			k.c = *s.CostCenterID
		}
		if i, ok := idx[k]; ok {
			out[i].Amount = out[i].Amount.Add(s.Amount)
			continue
		}
		idx[k] = len(out)
		out = append(out, s)
	}
	return out
}

// ruleInForce reports whether an allocation applies to a payroll period (the month of period).
func ruleInForce(start, end *time.Time, period time.Time) bool {
	first := time.Date(period.Year(), period.Month(), 1, 0, 0, 0, 0, time.UTC)
	last := first.AddDate(0, 1, -1)
	if start != nil && start.After(last) {
		return false
	}
	if end != nil && end.Before(first) {
		return false
	}
	return true
}

// buildCostAllocations loads, in three batched queries, the allocations in force, each
// employee's department and each department's cost center, and returns the run's gross pay
// attributed by (project, cost center).
func (d *Disburser) buildCostAllocations(ctx context.Context, tenantID uuid.UUID, period time.Time, slips []*ent.Payslip) ([]costShare, error) {
	if len(slips) == 0 {
		return nil, nil
	}
	empIDs := make([]uuid.UUID, 0, len(slips))
	for _, s := range slips {
		empIDs = append(empIDs, s.EmployeeID)
	}
	allocs, err := d.orm.EmployeeProjectAllocation.Query().
		Where(
			employeeprojectallocation.TenantID(tenantID),
			employeeprojectallocation.EmployeeIDIn(empIDs...),
			employeeprojectallocation.IsActive(true),
		).All(ctx)
	if err != nil {
		return nil, err
	}
	rulesByEmp := map[uuid.UUID][]allocRule{}
	for _, a := range allocs {
		if !ruleInForce(a.StartDate, a.EndDate, period) {
			continue
		}
		r := allocRule{ProjectID: a.ProjectID, CostCenterID: a.CostCenterID, Percent: a.AllocationPercent}
		if a.FixedAmount != nil && *a.FixedAmount > 0 {
			f := decimal.NewFromFloat(*a.FixedAmount)
			r.Fixed = &f
		}
		rulesByEmp[a.EmployeeID] = append(rulesByEmp[a.EmployeeID], r)
	}

	hr, err := d.orm.HRDetails.Query().
		Where(hrdetails.EmployeeIDIn(empIDs...), hrdetails.DepartmentIDNotNil()).
		Select(hrdetails.FieldEmployeeID, hrdetails.FieldDepartmentID).
		All(ctx)
	if err != nil {
		return nil, err
	}
	deptByEmp := map[uuid.UUID]uuid.UUID{}
	deptIDs := []uuid.UUID{}
	for _, h := range hr {
		if h.DepartmentID != nil {
			deptByEmp[h.EmployeeID] = *h.DepartmentID
			deptIDs = append(deptIDs, *h.DepartmentID)
		}
	}
	ccByDept := map[uuid.UUID]*uuid.UUID{}
	if len(deptIDs) > 0 {
		depts, err := d.orm.Department.Query().
			Where(department.IDIn(deptIDs...), department.CostCenterIDNotNil()).
			All(ctx)
		if err != nil {
			return nil, err
		}
		for _, dp := range depts {
			ccByDept[dp.ID] = dp.CostCenterID
		}
	}

	shares := []costShare{}
	for _, s := range slips {
		var deptCC *uuid.UUID
		if dep, ok := deptByEmp[s.EmployeeID]; ok {
			deptCC = ccByDept[dep]
		}
		shares = append(shares, splitGross(s.GrossPay, rulesByEmp[s.EmployeeID], deptCC)...)
	}
	return mergeShares(shares), nil
}

// allocationsPayload renders shares for the event (money as decimal strings, like the rest of
// the payroll payload).
func allocationsPayload(shares []costShare) []map[string]any {
	out := make([]map[string]any, 0, len(shares))
	for _, s := range shares {
		m := map[string]any{"amount": s.Amount.StringFixed(2)}
		if s.ProjectID != nil {
			m["project_id"] = s.ProjectID.String()
		}
		if s.CostCenterID != nil {
			m["cost_center_id"] = s.CostCenterID.String()
		}
		out = append(out, m)
	}
	return out
}
