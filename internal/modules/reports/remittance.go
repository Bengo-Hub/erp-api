package reports

import (
	"context"
	"errors"
	"sort"
	"strings"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebenefit"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
)

// ErrBadFilter is a report request missing a filter the report needs (the handler answers 400).
var ErrBadFilter = errors.New("reports: bad filter")

// remittanceColumns are the row keys of a check-off remittance schedule; erp-ui reads the same
// keys (src/lib/reports-config.ts) and the export uses them as columns.
var remittanceColumns = []string{"employee_name", "staff_number", "national_id", "employee_pin", "member_number", "amount"}

// Remittance is the check-off schedule an employer sends with a remittance to a SACCO, HELB, a
// union or any other body a deduction is paid to: for one deduction (Filter.Deduction, its payslip
// line code such as "sacco" or "helb", or its component id) and one period, each employee's
// amount actually deducted and their member or account number from their assignment.
//
// Only the deduction lines count. What net pay or the deduction limits left unrecovered is an
// informational shortfall line, not money withheld, so it is never on the schedule.
func (s *Service) Remittance(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	ded := strings.TrimSpace(f.Deduction)
	if ded == "" {
		return nil, errors.Join(ErrBadFilter, errors.New("deduction is required (a deduction code or component id)"))
	}
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	rep := &Report{Report: "remittance", Period: periodMeta(f), Columns: remittanceColumns, Rows: []map[string]any{}}
	slipEmp := make(map[uuid.UUID]uuid.UUID, len(slips))
	ids := make([]uuid.UUID, 0, len(slips))
	for _, p := range slips {
		slipEmp[p.ID] = p.EmployeeID
		ids = append(ids, p.ID)
	}

	match := payslipline.Code(ded)
	if id, perr := uuid.Parse(ded); perr == nil {
		match = payslipline.ComponentID(id)
	}
	perEmp := map[uuid.UUID]decimal.Decimal{}
	label := ""
	components := map[uuid.UUID]bool{}
	for _, chunk := range idChunks(ids) {
		lines, err := s.orm.PayslipLine.Query().
			Where(payslipline.TenantID(tenantID), payslipline.PayslipIDIn(chunk...),
				payslipline.Section("deduction_after_tax"), match).
			All(ctx)
		if err != nil {
			return nil, err
		}
		for _, l := range lines {
			emp := slipEmp[l.PayslipID]
			perEmp[emp] = perEmp[emp].Add(l.CashAmount)
			if label == "" {
				label = l.Label
			}
			if l.ComponentID != nil {
				components[*l.ComponentID] = true
			}
		}
	}

	empIDs := make([]uuid.UUID, 0, len(perEmp))
	for id := range perEmp {
		empIDs = append(empIDs, id)
	}
	emps := map[uuid.UUID]*ent.Employee{}
	refs := map[uuid.UUID]string{}
	for _, chunk := range idChunks(empIDs) {
		rows, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(chunk...)).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, e := range rows {
			emps[e.ID] = e
		}
		if len(components) == 0 {
			continue
		}
		compIDs := make([]uuid.UUID, 0, len(components))
		for id := range components {
			compIDs = append(compIDs, id)
		}
		// The member or account number is on the employee's assignment of this deduction; the
		// newest assignment wins when there are several.
		bens, err := s.orm.EmployeeBenefit.Query().
			Where(employeebenefit.TenantID(tenantID), employeebenefit.EmployeeIDIn(chunk...), employeebenefit.ComponentIDIn(compIDs...)).
			Order(ent.Asc(employeebenefit.FieldCreatedAt)).
			All(ctx)
		if err != nil {
			return nil, err
		}
		for _, b := range bens {
			if ref, ok := b.Metadata["reference"].(string); ok && strings.TrimSpace(ref) != "" {
				refs[b.EmployeeID] = strings.TrimSpace(ref)
			}
		}
	}

	total := decimal.Zero
	for _, id := range empIDs {
		amt := perEmp[id]
		if !amt.IsPositive() {
			continue
		}
		e := emps[id]
		staff := ""
		if e != nil && e.EmployeeNumber != nil {
			staff = *e.EmployeeNumber
		}
		rep.Rows = append(rep.Rows, map[string]any{
			"employee_name": empName(e),
			"staff_number":  staff,
			"national_id":   natID(e),
			"employee_pin":  pin(e),
			"member_number": refs[id],
			"amount":        money(amt),
		})
		total = total.Add(amt)
	}
	sort.SliceStable(rep.Rows, func(i, j int) bool {
		return rep.Rows[i]["employee_name"].(string) < rep.Rows[j]["employee_name"].(string)
	})
	rep.Totals = map[string]any{"count": len(rep.Rows), "amount": money(total), "deduction": label}
	return rep, nil
}
