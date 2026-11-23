package payroll

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/companysettings"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/pieceoutput"
	"github.com/Bengo-Hub/erp-api/internal/ent/piecerate"
)

// Piece work: rates per unit of an operation or item, output recorded per employee and day,
// reviewed by HR or a supervisor, and paid as an earning in the run of its month.

// Piece work errors, mapped to HTTP statuses by the handler.
var (
	ErrPieceRateNotFound = errors.New("payroll: piece rate not found")
	ErrPieceRateInactive = errors.New("payroll: the piece rate is not in effect on that date")
)

// PieceRateInput is the create/patch payload; nil fields stay unchanged on patch.
type PieceRateInput struct {
	Code          *string
	Name          *string
	Unit          *string
	Rate          *decimal.Decimal
	Currency      *string
	DepartmentID  *uuid.UUID
	EffectiveFrom *time.Time
	EffectiveTo   *time.Time
	Active        *bool
}

// ListPieceRates returns the tenant's piece rates (active only when activeOnly).
func (s *Service) ListPieceRates(ctx context.Context, tenantID uuid.UUID, activeOnly bool) ([]*ent.PieceRate, error) {
	q := s.orm.PieceRate.Query().Where(piecerate.TenantID(tenantID))
	if activeOnly {
		q = q.Where(piecerate.Active(true))
	}
	return q.Order(ent.Asc(piecerate.FieldCode), ent.Desc(piecerate.FieldEffectiveFrom)).All(ctx)
}

// tenantCurrency is the company's default currency (KES when unset).
func (s *Service) tenantCurrency(ctx context.Context, tenantID uuid.UUID) string {
	cs, err := s.orm.CompanySettings.Query().Where(companysettings.TenantID(tenantID)).First(ctx)
	if err == nil && cs.DefaultCurrency != "" {
		return cs.DefaultCurrency
	}
	return "KES"
}

// CreatePieceRate adds a piece rate.
func (s *Service) CreatePieceRate(ctx context.Context, tenantID uuid.UUID, in PieceRateInput) (*ent.PieceRate, error) {
	if in.Code == nil || in.Name == nil || in.Unit == nil || in.Rate == nil || in.EffectiveFrom == nil ||
		strings.TrimSpace(*in.Code) == "" || strings.TrimSpace(*in.Name) == "" || strings.TrimSpace(*in.Unit) == "" {
		return nil, errors.New("code, name, unit, rate and effective_from are required")
	}
	if !in.Rate.IsPositive() {
		return nil, errors.New("rate must be above 0")
	}
	if in.EffectiveTo != nil && in.EffectiveTo.Before(*in.EffectiveFrom) {
		return nil, errors.New("effective_to must not be before effective_from")
	}
	currency := s.tenantCurrency(ctx, tenantID)
	if in.Currency != nil && strings.TrimSpace(*in.Currency) != "" {
		currency = strings.ToUpper(strings.TrimSpace(*in.Currency))
	}
	b := s.orm.PieceRate.Create().SetTenantID(tenantID).SetCode(strings.TrimSpace(*in.Code)).
		SetName(strings.TrimSpace(*in.Name)).SetUnit(strings.TrimSpace(*in.Unit)).SetRate(*in.Rate).
		SetCurrency(currency).SetNillableDepartmentID(in.DepartmentID).SetEffectiveFrom(dayOf(*in.EffectiveFrom))
	if in.EffectiveTo != nil {
		b = b.SetEffectiveTo(dayOf(*in.EffectiveTo))
	}
	if in.Active != nil {
		b = b.SetActive(*in.Active)
	}
	return b.Save(ctx)
}

// UpdatePieceRate patches a piece rate. Output already recorded keeps its rate snapshot.
func (s *Service) UpdatePieceRate(ctx context.Context, tenantID, id uuid.UUID, in PieceRateInput) (*ent.PieceRate, error) {
	pr, err := s.orm.PieceRate.Query().Where(piecerate.TenantID(tenantID), piecerate.ID(id)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, ErrPieceRateNotFound
	}
	if err != nil {
		return nil, err
	}
	u := pr.Update()
	if in.Code != nil {
		u = u.SetCode(strings.TrimSpace(*in.Code))
	}
	if in.Name != nil {
		u = u.SetName(strings.TrimSpace(*in.Name))
	}
	if in.Unit != nil {
		u = u.SetUnit(strings.TrimSpace(*in.Unit))
	}
	if in.Rate != nil {
		if !in.Rate.IsPositive() {
			return nil, errors.New("rate must be above 0")
		}
		u = u.SetRate(*in.Rate)
	}
	if in.Currency != nil {
		u = u.SetCurrency(strings.ToUpper(strings.TrimSpace(*in.Currency)))
	}
	if in.DepartmentID != nil {
		u = u.SetDepartmentID(*in.DepartmentID)
	}
	if in.EffectiveFrom != nil {
		u = u.SetEffectiveFrom(dayOf(*in.EffectiveFrom))
	}
	if in.EffectiveTo != nil {
		u = u.SetEffectiveTo(dayOf(*in.EffectiveTo))
	}
	if in.Active != nil {
		u = u.SetActive(*in.Active)
	}
	return u.Save(ctx)
}

// DeletePieceRate removes a piece rate that has no output recorded against it; one in use is
// deactivated instead so history stays readable.
func (s *Service) DeletePieceRate(ctx context.Context, tenantID, id uuid.UUID) error {
	used, err := s.orm.PieceOutput.Query().Where(pieceoutput.TenantID(tenantID), pieceoutput.PieceRateID(id)).Exist(ctx)
	if err != nil {
		return err
	}
	if used {
		n, err := s.orm.PieceRate.Update().Where(piecerate.TenantID(tenantID), piecerate.ID(id)).SetActive(false).Save(ctx)
		if err == nil && n == 0 {
			return ErrPieceRateNotFound
		}
		return err
	}
	n, err := s.orm.PieceRate.Delete().Where(piecerate.TenantID(tenantID), piecerate.ID(id)).Exec(ctx)
	if err == nil && n == 0 {
		return ErrPieceRateNotFound
	}
	return err
}

func dayOf(t time.Time) time.Time {
	y, m, d := t.UTC().Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

// pieceAmount is (quantity - rejected) x rate, never below zero. Pure.
func pieceAmount(qty, rejected, rate decimal.Decimal) decimal.Decimal {
	paid := qty.Sub(rejected)
	if paid.IsNegative() {
		paid = decimal.Zero
	}
	return paid.Mul(rate).Round(2)
}

// PieceOutputInput records output for an employee and day.
type PieceOutputInput struct {
	EmployeeID       uuid.UUID
	PieceRateID      uuid.UUID
	Date             time.Time
	Quantity         decimal.Decimal
	RejectedQuantity decimal.Decimal
	Note             string
	RecordedBy       *uuid.UUID
}

// PieceOutputView is a piece output row for lists.
type PieceOutputView struct {
	*ent.PieceOutput
	EmployeeName  string `json:"employee_name"`
	PieceRateName string `json:"piece_rate_name"`
	Unit          string `json:"unit"`
}

// CreatePieceOutput records pending output at the rate in effect on the day.
func (s *Service) CreatePieceOutput(ctx context.Context, tenantID uuid.UUID, in PieceOutputInput) (*PieceOutputView, error) {
	if !in.Quantity.IsPositive() || in.RejectedQuantity.IsNegative() || in.RejectedQuantity.GreaterThan(in.Quantity) {
		return nil, errors.New("quantity must be above 0 and rejected_quantity between 0 and quantity")
	}
	day := dayOf(in.Date)
	pr, err := s.orm.PieceRate.Query().Where(piecerate.TenantID(tenantID), piecerate.ID(in.PieceRateID)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, ErrPieceRateNotFound
	}
	if err != nil {
		return nil, err
	}
	if !pr.Active || day.Before(dayOf(pr.EffectiveFrom)) || (pr.EffectiveTo != nil && day.After(dayOf(*pr.EffectiveTo))) {
		return nil, ErrPieceRateInactive
	}
	emp, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.ID(in.EmployeeID)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("payroll: employee not found")
	}
	row, err := s.orm.PieceOutput.Create().SetTenantID(tenantID).SetEmployeeID(emp.ID).SetPieceRateID(pr.ID).
		SetDate(day).SetQuantity(in.Quantity).SetRejectedQuantity(in.RejectedQuantity).SetRate(pr.Rate).
		SetAmount(pieceAmount(in.Quantity, in.RejectedQuantity, pr.Rate)).SetCurrency(pr.Currency).
		SetNote(strings.TrimSpace(in.Note)).SetNillableRecordedBy(in.RecordedBy).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("payroll: record piece output: %w", err)
	}
	return &PieceOutputView{PieceOutput: row, EmployeeName: strings.TrimSpace(emp.FirstName + " " + emp.LastName),
		PieceRateName: pr.Name, Unit: pr.Unit}, nil
}

// PieceOutputFilter narrows a piece output list.
type PieceOutputFilter struct {
	EmployeeID  *uuid.UUID
	PieceRateID *uuid.UUID
	Status      string
	From, To    time.Time
}

// ListPieceOutputs returns one page of output, newest first, with names.
func (s *Service) ListPieceOutputs(ctx context.Context, tenantID uuid.UUID, f PieceOutputFilter, limit, offset int) ([]PieceOutputView, int, error) {
	q := s.orm.PieceOutput.Query().Where(pieceoutput.TenantID(tenantID),
		pieceoutput.DateGTE(dayOf(f.From)), pieceoutput.DateLT(dayOf(f.To).AddDate(0, 0, 1)))
	if f.EmployeeID != nil {
		q = q.Where(pieceoutput.EmployeeID(*f.EmployeeID))
	}
	if f.PieceRateID != nil {
		q = q.Where(pieceoutput.PieceRateID(*f.PieceRateID))
	}
	if f.Status != "" {
		q = q.Where(pieceoutput.StatusEQ(pieceoutput.Status(f.Status)))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, err
	}
	rows, err := q.Order(ent.Desc(pieceoutput.FieldDate), ent.Desc(pieceoutput.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, err
	}
	empIDs, rateIDs := []uuid.UUID{}, []uuid.UUID{}
	for _, r := range rows {
		empIDs = append(empIDs, r.EmployeeID)
		rateIDs = append(rateIDs, r.PieceRateID)
	}
	names := map[uuid.UUID]string{}
	if len(empIDs) > 0 {
		emps, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(empIDs...)).
			Select(employee.FieldID, employee.FieldFirstName, employee.FieldLastName).All(ctx)
		if err != nil {
			return nil, 0, err
		}
		for _, e := range emps {
			names[e.ID] = strings.TrimSpace(e.FirstName + " " + e.LastName)
		}
	}
	rates := map[uuid.UUID]*ent.PieceRate{}
	if len(rateIDs) > 0 {
		prs, err := s.orm.PieceRate.Query().Where(piecerate.TenantID(tenantID), piecerate.IDIn(rateIDs...)).All(ctx)
		if err != nil {
			return nil, 0, err
		}
		for _, p := range prs {
			rates[p.ID] = p
		}
	}
	out := make([]PieceOutputView, len(rows))
	for i, r := range rows {
		v := PieceOutputView{PieceOutput: r, EmployeeName: names[r.EmployeeID]}
		if p := rates[r.PieceRateID]; p != nil {
			v.PieceRateName, v.Unit = p.Name, p.Unit
		}
		out[i] = v
	}
	return out, total, nil
}

// ReviewPieceOutputs approves or rejects pending output. Paid output is never changed.
func (s *Service) ReviewPieceOutputs(ctx context.Context, tenantID uuid.UUID, reviewer *uuid.UUID, ids []uuid.UUID, action string) (int, error) {
	st := pieceoutput.StatusApproved
	switch action {
	case "approve":
	case "reject":
		st = pieceoutput.StatusRejected
	default:
		return 0, errors.New("action must be approve or reject")
	}
	if len(ids) == 0 {
		return 0, errors.New("ids are required")
	}
	return s.orm.PieceOutput.Update().Where(pieceoutput.TenantID(tenantID), pieceoutput.IDIn(ids...),
		pieceoutput.StatusEQ(pieceoutput.StatusPending)).
		SetStatus(st).SetNillableReviewedBy(reviewer).SetReviewedAt(time.Now().UTC()).Save(ctx)
}

// approvedPieceOutputs returns the month's approved (or already paid) output per employee.
func (s *Service) approvedPieceOutputs(ctx context.Context, tenantID uuid.UUID, period time.Time) (map[uuid.UUID][]*ent.PieceOutput, error) {
	from := dayOf(period)
	from = time.Date(from.Year(), from.Month(), 1, 0, 0, 0, 0, time.UTC)
	rows, err := s.orm.PieceOutput.Query().Where(pieceoutput.TenantID(tenantID),
		pieceoutput.DateGTE(from), pieceoutput.DateLT(from.AddDate(0, 1, 0)),
		pieceoutput.StatusIn(pieceoutput.StatusApproved, pieceoutput.StatusPaid)).All(ctx)
	if err != nil {
		return nil, err
	}
	out := map[uuid.UUID][]*ent.PieceOutput{}
	for _, r := range rows {
		out[r.EmployeeID] = append(out[r.EmployeeID], r)
	}
	return out, nil
}

// markPieceOutputsPaid links the month's paid output to its payslip.
func (s *Service) markPieceOutputsPaid(ctx context.Context, tenantID, payslipID uuid.UUID, ids []uuid.UUID) error {
	if len(ids) == 0 {
		return nil
	}
	return s.orm.PieceOutput.Update().Where(pieceoutput.TenantID(tenantID), pieceoutput.IDIn(ids...),
		pieceoutput.StatusIn(pieceoutput.StatusApproved, pieceoutput.StatusPaid)).
		SetStatus(pieceoutput.StatusPaid).SetPayslipID(payslipID).Exec(ctx)
}
