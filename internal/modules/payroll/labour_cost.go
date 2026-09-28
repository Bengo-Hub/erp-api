package payroll

import (
	"context"
	"fmt"
	"sort"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
)

// ProjectLabourCost is one project's share of a month's gross pay (nil project: pay not
// allocated to any project).
type ProjectLabourCost struct {
	ProjectID *uuid.UUID      `json:"project_id"`
	Amount    decimal.Decimal `json:"amount"`
	SharePct  float64         `json:"share_pct"`
}

// LabourCostReport is a payroll month split by project.
type LabourCostReport struct {
	Month      string              `json:"month"`
	TotalGross decimal.Decimal     `json:"total_gross"`
	Projects   []ProjectLabourCost `json:"projects"`
}

// ProjectLabourCost splits a payroll month's gross pay by project with the same allocation rules
// the payroll event posts to treasury (costAllocations), so the report agrees with the project
// actuals in finance. Payslips load only employee and gross, so the cost follows headcount.
func (s *Service) ProjectLabourCost(ctx context.Context, tenantID uuid.UUID, month time.Time) (*LabourCostReport, error) {
	first := time.Date(month.Year(), month.Month(), 1, 0, 0, 0, 0, time.UTC)
	var rows []struct {
		ID         uuid.UUID       `json:"id"`
		EmployeeID uuid.UUID       `json:"employee_id"`
		GrossPay   decimal.Decimal `json:"gross_pay"`
	}
	if err := s.orm.Payslip.Query().
		Where(payslip.TenantID(tenantID), payslip.DeleteStatus(false),
			payslip.PaymentPeriodGTE(first), payslip.PaymentPeriodLT(first.AddDate(0, 1, 0))).
		Select(payslip.FieldID, payslip.FieldEmployeeID, payslip.FieldGrossPay).
		Scan(ctx, &rows); err != nil {
		return nil, fmt.Errorf("payroll: labour cost payslips: %w", err)
	}
	slips := make([]*ent.Payslip, len(rows))
	total := decimal.Zero
	for i, r := range rows {
		slips[i] = &ent.Payslip{ID: r.ID, EmployeeID: r.EmployeeID, GrossPay: r.GrossPay}
		total = total.Add(r.GrossPay)
	}
	shares, err := costAllocations(ctx, s.orm, tenantID, first, slips)
	if err != nil {
		return nil, fmt.Errorf("payroll: labour cost allocations: %w", err)
	}
	byProject := map[uuid.UUID]*ProjectLabourCost{}
	unallocated := &ProjectLabourCost{}
	for _, sh := range shares {
		row := unallocated
		if sh.ProjectID != nil {
			if byProject[*sh.ProjectID] == nil {
				id := *sh.ProjectID
				byProject[id] = &ProjectLabourCost{ProjectID: &id}
			}
			row = byProject[*sh.ProjectID]
		}
		row.Amount = row.Amount.Add(sh.Amount)
	}
	out := &LabourCostReport{Month: first.Format("2006-01"), TotalGross: total.Round(2), Projects: []ProjectLabourCost{}}
	for _, p := range byProject {
		out.Projects = append(out.Projects, *p)
	}
	sort.Slice(out.Projects, func(i, j int) bool { return out.Projects[i].Amount.GreaterThan(out.Projects[j].Amount) })
	if unallocated.Amount.IsPositive() {
		out.Projects = append(out.Projects, *unallocated)
	}
	for i := range out.Projects {
		out.Projects[i].Amount = out.Projects[i].Amount.Round(2)
		if total.IsPositive() {
			out.Projects[i].SharePct = out.Projects[i].Amount.Div(total).Mul(hundred).Round(1).InexactFloat64()
		}
	}
	return out, nil
}
