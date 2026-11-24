package payrollsettings

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebenefit"
)

// Per-employee component assignments. An organisation switches opt-in earnings and deductions on
// in its payroll settings; each employee is then given the ones that apply to them, with their
// own amount or percentage, months and reference. Assignments are EmployeeBenefit rows (the
// table the legacy system already used for per-employee benefits): the component's category says
// how a payroll run applies the row, and the values the row has no column for are kept in its
// metadata.

// Assignment metadata keys.
const (
	metaPercentage = "percentage"
	metaPercentOf  = "percent_of"
	metaReference  = "reference"
)

// Percentage bases.
const (
	PercentOfBasic = "basic"
	PercentOfGross = "gross"
)

// ErrNotAssignable is returned when a component cannot be given to an employee: it is switched
// off for the organisation, statutory, or driven by its own module (loans, overtime and so on).
var ErrNotAssignable = errors.New("this component cannot be assigned to an employee")

// Assignable reports whether a resolved component can be given to employees one by one: switched
// on for the tenant, not statutory and not driven by its own module.
func Assignable(rc ResolvedComponent) bool {
	if !rc.Active || rc.Statutory || rc.ManagedBy != "" || rc.Component == nil {
		return false
	}
	switch rc.Component.Category {
	case CategoryEarnings, CategoryDeductions, CategoryBenefits:
		return true
	}
	return false
}

// AssignmentTerms is how an assignment's amount is worked out for a period.
type AssignmentTerms struct {
	Amount     decimal.Decimal // fixed monthly amount (used when Percentage is zero)
	Percentage decimal.Decimal // percent of Base (e.g. 10 = 10%)
	Base       string          // basic | gross
	Reference  string
}

// Terms reads an assignment's terms: its own percentage or amount first, then the component's
// default amount, then the component's default percentage.
func Terms(b *ent.EmployeeBenefit, rc ResolvedComponent) AssignmentTerms {
	t := AssignmentTerms{Base: PercentOfBasic}
	if rc.Component != nil && rc.Component.PercentOf == PercentOfGross {
		t.Base = PercentOfGross
	}
	if b.Metadata != nil {
		if s, ok := b.Metadata[metaPercentOf].(string); ok && (s == PercentOfBasic || s == PercentOfGross) {
			t.Base = s
		}
		if s, ok := b.Metadata[metaReference].(string); ok {
			t.Reference = s
		}
		if p := metaDecimal(b.Metadata[metaPercentage]); p.IsPositive() {
			t.Percentage = p
			return t
		}
	}
	switch {
	case b.Amount.IsPositive():
		t.Amount = b.Amount
	case rc.Amount.IsPositive():
		t.Amount = rc.Amount
	case rc.Percentage.IsPositive():
		t.Percentage = rc.Percentage
	}
	return t
}

// For returns the period amount given the employee's basic pay and gross pay (basic plus the
// fixed and basic-based component earnings), rounded to cents.
func (t AssignmentTerms) For(basic, gross decimal.Decimal) decimal.Decimal {
	if t.Percentage.IsPositive() {
		base := basic
		if t.Base == PercentOfGross {
			base = gross
		}
		return base.Mul(t.Percentage).Div(decimal.NewFromInt(100)).Round(2)
	}
	return t.Amount.Round(2)
}

// Assignment is one component given to an employee, with the component as the tenant sees it.
type Assignment struct {
	Row       *ent.EmployeeBenefit
	Component *ResolvedComponent // nil when the component no longer exists
	Terms     AssignmentTerms
}

// AssignmentInput is the create or update payload. Exactly one of Amount and Percentage is used;
// when both are empty the component's default applies. Months are normalised to their first day.
type AssignmentInput struct {
	ComponentID uuid.UUID
	Amount      *decimal.Decimal
	Percentage  *decimal.Decimal
	PercentOf   string
	Reference   string
	StartMonth  *time.Time
	EndMonth    *time.Time
	IsActive    *bool
}

// ListAssignments returns the employee's assigned components, newest first.
func (s *Service) ListAssignments(ctx context.Context, tenantID, employeeID uuid.UUID) ([]Assignment, error) {
	rows, err := s.orm.EmployeeBenefit.Query().
		Where(employeebenefit.TenantID(tenantID), employeebenefit.EmployeeID(employeeID)).
		Order(ent.Desc(employeebenefit.FieldCreatedAt)).All(ctx)
	if err != nil {
		return nil, err
	}
	ids := make([]uuid.UUID, 0, len(rows))
	for _, r := range rows {
		if r.ComponentID != nil {
			ids = append(ids, *r.ComponentID)
		}
	}
	comps, err := s.ComponentsByID(ctx, tenantID, ids)
	if err != nil {
		return nil, err
	}
	out := make([]Assignment, 0, len(rows))
	for _, r := range rows {
		a := Assignment{Row: r}
		if r.ComponentID != nil {
			if rc, ok := comps[*r.ComponentID]; ok {
				a.Component = &rc
				a.Terms = Terms(r, rc)
			}
		}
		if a.Component == nil {
			a.Terms = Terms(r, ResolvedComponent{})
		}
		out = append(out, a)
	}
	return out, nil
}

// SaveAssignment creates (id nil) or updates an employee's component assignment after checking
// that the component is switched on and assignable, the values fit its category and the months
// do not overlap another assignment of the same component.
func (s *Service) SaveAssignment(ctx context.Context, tenantID, employeeID uuid.UUID, id *uuid.UUID, in AssignmentInput) (*Assignment, error) {
	ok, err := s.orm.Employee.Query().Where(employee.ID(employeeID), employee.TenantID(tenantID)).Exist(ctx)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, ErrNotFound
	}
	var cur *ent.EmployeeBenefit
	if id != nil {
		cur, err = s.orm.EmployeeBenefit.Query().Where(employeebenefit.ID(*id),
			employeebenefit.TenantID(tenantID), employeebenefit.EmployeeID(employeeID)).Only(ctx)
		if ent.IsNotFound(err) {
			return nil, ErrNotFound
		}
		if err != nil {
			return nil, err
		}
		if in.ComponentID == uuid.Nil && cur.ComponentID != nil {
			in.ComponentID = *cur.ComponentID
		}
	}
	rc, err := s.Component(ctx, tenantID, in.ComponentID)
	if err != nil {
		return nil, err
	}
	if !Assignable(*rc) {
		if !rc.Active {
			return nil, fmt.Errorf("%w: %s is switched off for your organisation", ErrNotAssignable, rc.Title)
		}
		return nil, fmt.Errorf("%w: %s is applied by payroll itself", ErrNotAssignable, rc.Title)
	}

	meta, amount, err := assignmentValues(in, *rc)
	if err != nil {
		return nil, err
	}
	start, end := monthStart(in.StartMonth), monthStart(in.EndMonth)
	if start != nil && end != nil && end.Before(*start) {
		return nil, fmt.Errorf("the end month is before the start month")
	}
	active := in.IsActive == nil || *in.IsActive
	if cur != nil && in.IsActive == nil {
		active = cur.IsActive
	}
	if active {
		if err := s.checkOverlap(ctx, tenantID, employeeID, rc, id, start, end); err != nil {
			return nil, err
		}
	}

	var row *ent.EmployeeBenefit
	if cur == nil {
		c := s.orm.EmployeeBenefit.Create().
			SetTenantID(tenantID).SetEmployeeID(employeeID).SetComponentID(rc.Component.ID).
			SetAmount(amount).SetNonCash(rc.Component.NonCash).SetIsActive(active).
			SetMetadata(meta).SetNillableEffectiveDate(start).SetNillableEndDate(end)
		row, err = c.Save(ctx)
	} else {
		u := cur.Update().SetComponentID(rc.Component.ID).SetAmount(amount).
			SetNonCash(rc.Component.NonCash).SetIsActive(active).SetMetadata(meta)
		if start != nil {
			u = u.SetEffectiveDate(*start)
		} else {
			u = u.ClearEffectiveDate()
		}
		if end != nil {
			u = u.SetEndDate(*end)
		} else {
			u = u.ClearEndDate()
		}
		row, err = u.Save(ctx)
	}
	if err != nil {
		return nil, err
	}
	return &Assignment{Row: row, Component: rc, Terms: Terms(row, *rc)}, nil
}

// assignmentValues validates the amount, percentage and reference for the component and returns
// the row's metadata and fixed amount.
func assignmentValues(in AssignmentInput, rc ResolvedComponent) (map[string]any, decimal.Decimal, error) {
	meta := map[string]any{}
	amount := decimal.Zero
	hasAmount := in.Amount != nil && !in.Amount.IsZero()
	hasPct := in.Percentage != nil && !in.Percentage.IsZero()
	switch {
	case hasAmount && hasPct:
		return nil, amount, fmt.Errorf("give an amount or a percentage, not both")
	case hasAmount:
		if in.Amount.IsNegative() {
			return nil, amount, fmt.Errorf("the amount cannot be negative")
		}
		amount = in.Amount.Round(2)
	case hasPct:
		if in.Percentage.IsNegative() || in.Percentage.GreaterThan(decimal.NewFromInt(100)) {
			return nil, amount, fmt.Errorf("the percentage must be between 0 and 100")
		}
		if rc.Component.Category == CategoryBenefits {
			return nil, amount, fmt.Errorf("a benefit takes a fixed monthly value, not a percentage")
		}
		meta[metaPercentage] = in.Percentage.StringFixed(4)
		base := strings.ToLower(strings.TrimSpace(in.PercentOf))
		if base == "" {
			base = rc.Component.PercentOf
		}
		if base != PercentOfGross {
			base = PercentOfBasic
		}
		meta[metaPercentOf] = base
	default:
		if !rc.Amount.IsPositive() && !rc.Percentage.IsPositive() {
			return nil, amount, fmt.Errorf("%s has no default amount or rate: give an amount or a percentage", rc.Title)
		}
	}
	ref := strings.TrimSpace(in.Reference)
	if label := ReferenceLabel(rc.Code); label != "" && ref == "" && rc.Component.Category == CategoryDeductions {
		return nil, amount, fmt.Errorf("%s is required for %s", label, rc.Title)
	}
	if ref != "" {
		meta[metaReference] = ref
	}
	return meta, amount, nil
}

// checkOverlap refuses a second active assignment of the same component whose months overlap.
func (s *Service) checkOverlap(ctx context.Context, tenantID, employeeID uuid.UUID, rc *ResolvedComponent, self *uuid.UUID, start, end *time.Time) error {
	q := s.orm.EmployeeBenefit.Query().Where(employeebenefit.TenantID(tenantID),
		employeebenefit.EmployeeID(employeeID), employeebenefit.ComponentID(rc.Component.ID),
		employeebenefit.IsActive(true))
	if self != nil {
		q = q.Where(employeebenefit.IDNEQ(*self))
	}
	others, err := q.All(ctx)
	if err != nil {
		return err
	}
	for _, o := range others {
		if monthsOverlap(start, end, o.EffectiveDate, o.EndDate) {
			return fmt.Errorf("%s is already assigned to this employee for some of these months", rc.Title)
		}
	}
	return nil
}

// monthsOverlap reports whether two month ranges (nil bounds open) share a month.
func monthsOverlap(aStart, aEnd, bStart, bEnd *time.Time) bool {
	if aEnd != nil && bStart != nil && aEnd.Before(*bStart) {
		return false
	}
	if bEnd != nil && aStart != nil && bEnd.Before(*aStart) {
		return false
	}
	return true
}

// DeleteAssignment removes an employee's component assignment. Payslips already generated keep
// their lines.
func (s *Service) DeleteAssignment(ctx context.Context, tenantID, employeeID, id uuid.UUID) error {
	n, err := s.orm.EmployeeBenefit.Delete().Where(employeebenefit.ID(id),
		employeebenefit.TenantID(tenantID), employeebenefit.EmployeeID(employeeID)).Exec(ctx)
	if err != nil {
		return err
	}
	if n == 0 {
		return ErrNotFound
	}
	return nil
}

// monthStart returns the first day (UTC) of t's month, or nil.
func monthStart(t *time.Time) *time.Time {
	if t == nil || t.IsZero() {
		return nil
	}
	m := time.Date(t.Year(), t.Month(), 1, 0, 0, 0, 0, time.UTC)
	return &m
}
