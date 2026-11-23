package attendance

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalrequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/overtimerequest"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
)

// ErrOvertimeApplicationsOff is returned to staff when the tenant's ESS settings do not allow
// overtime applications.
var ErrOvertimeApplicationsOff = errors.New("attendance: overtime applications are switched off for staff")

// maxOvertimeRequestHours bounds one day's request.
var maxOvertimeRequestHours = decimal.NewFromInt(24)

// OvertimeInput is an overtime request for a day.
type OvertimeInput struct {
	EmployeeID  uuid.UUID
	Date        time.Time
	Hours       decimal.Decimal
	Reason      string
	RequestedBy *uuid.UUID
	Self        bool // filed by the employee through ESS (subject to allow_overtime_application)
}

// OvertimeView is an overtime request row for lists.
type OvertimeView struct {
	*ent.OvertimeRequest
	EmployeeName string `json:"employee_name"`
}

// CreateOvertimeRequest records an overtime request and submits it for approval.
func (s *Service) CreateOvertimeRequest(ctx context.Context, tenantID uuid.UUID, in OvertimeInput) (*OvertimeView, error) {
	if s.approvals == nil {
		return nil, ErrApprovalsUnavailable
	}
	if !in.Hours.IsPositive() || in.Hours.GreaterThan(maxOvertimeRequestHours) {
		return nil, errors.New("hours must be above 0 and at most 24")
	}
	if in.Date.IsZero() {
		return nil, errors.New("date is required")
	}
	if in.Self {
		ess, err := s.GetESSSettings(ctx, tenantID)
		if err != nil {
			return nil, err
		}
		if !ess.AllowOvertimeApplication {
			return nil, ErrOvertimeApplicationsOff
		}
	}
	emp, err := s.loadEmployee(ctx, tenantID, in.EmployeeID)
	if err != nil {
		return nil, err
	}
	date := dateOnly(in.Date)
	row, err := s.orm.OvertimeRequest.Create().SetTenantID(tenantID).SetEmployeeID(emp.ID).SetDate(date).
		SetHours(in.Hours.Round(2)).SetReason(strings.TrimSpace(in.Reason)).
		SetNillableRequestedBy(in.RequestedBy).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create overtime request: %w", err)
	}
	req, err := s.approvals.SubmitWithFallback(ctx, tenantID, approvals.SubmitInput{
		Module: ModuleOvertime, ObjectID: row.ID,
		ObjectReference:     fmt.Sprintf("Overtime %s %s (%s h)", employeeName(emp), date.Format("2006-01-02"), in.Hours.Round(2)),
		RequesterEmployeeID: &emp.ID, SubmittedBy: in.RequestedBy,
	}, fallbackApproverRole)
	if err != nil {
		return nil, fmt.Errorf("attendance: submit overtime request: %w", err)
	}
	if row, err = row.Update().SetApprovalRequestID(req.ID).Save(ctx); err != nil {
		return nil, fmt.Errorf("attendance: link approval: %w", err)
	}
	return &OvertimeView{OvertimeRequest: row, EmployeeName: employeeName(emp)}, nil
}

// ListOvertimeRequests returns one page of overtime requests, newest first, over a bounded range.
func (s *Service) ListOvertimeRequests(ctx context.Context, tenantID uuid.UUID, f CorrectionFilter, limit, offset int) ([]OvertimeView, int, error) {
	lo, hi := boundRange(f.From, f.To, time.Now())
	q := s.orm.OvertimeRequest.Query().Where(overtimerequest.TenantID(tenantID),
		overtimerequest.DateGTE(lo), overtimerequest.DateLT(hi.AddDate(0, 0, 1)))
	if f.EmployeeID != nil {
		q = q.Where(overtimerequest.EmployeeID(*f.EmployeeID))
	}
	if f.Status != "" {
		q = q.Where(overtimerequest.StatusEQ(overtimerequest.Status(f.Status)))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("attendance: count overtime requests: %w", err)
	}
	rows, err := q.Order(ent.Desc(overtimerequest.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("attendance: list overtime requests: %w", err)
	}
	ids := make([]uuid.UUID, len(rows))
	for i, r := range rows {
		ids[i] = r.EmployeeID
	}
	names := s.employeeNames(ctx, tenantID, ids)
	out := make([]OvertimeView, len(rows))
	for i, r := range rows {
		out[i] = OvertimeView{OvertimeRequest: r, EmployeeName: names[r.EmployeeID]}
	}
	return out, total, nil
}

// applyOvertimeDecision is the approvals hook: it records the outcome on the request and emits
// erp.attendance.overtime.approved or .rejected. Idempotent once decided.
func (s *Service) applyOvertimeDecision(ctx context.Context, tenantID uuid.UUID, req *ent.ApprovalRequest) error {
	row, err := s.orm.OvertimeRequest.Query().Where(overtimerequest.TenantID(tenantID),
		overtimerequest.ID(req.ObjectID)).Only(ctx)
	if err != nil {
		return fmt.Errorf("load overtime request: %w", err)
	}
	if row.Status != overtimerequest.StatusPending {
		return nil
	}
	st, event := overtimerequest.StatusRejected, "attendance.overtime.rejected"
	switch req.Status {
	case approvalrequest.StatusApproved:
		st, event = overtimerequest.StatusApproved, "attendance.overtime.approved"
	case approvalrequest.StatusCancelled:
		st, event = overtimerequest.StatusCancelled, "attendance.overtime.cancelled"
	}
	if err := row.Update().SetStatus(st).SetDecidedAt(time.Now().UTC()).Exec(ctx); err != nil {
		return fmt.Errorf("decide overtime request: %w", err)
	}
	s.publish(ctx, tenantID, row.ID, event, map[string]any{
		"overtime_request_id": row.ID.String(), "employee_id": row.EmployeeID.String(),
		"date": dateOnly(row.Date).Format("2006-01-02"), "hours": row.Hours.String(),
	})
	return nil
}

// ApprovedOvertime sums approved overtime request hours per employee day in [from, to].
func (s *Service) ApprovedOvertime(ctx context.Context, tenantID uuid.UUID, from, to time.Time) (map[uuid.UUID]map[time.Time]decimal.Decimal, error) {
	rows, err := s.orm.OvertimeRequest.Query().Where(overtimerequest.TenantID(tenantID),
		overtimerequest.StatusEQ(overtimerequest.StatusApproved),
		overtimerequest.DateGTE(dateOnly(from)), overtimerequest.DateLT(dateOnly(to).AddDate(0, 0, 1))).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: approved overtime: %w", err)
	}
	out := map[uuid.UUID]map[time.Time]decimal.Decimal{}
	for _, r := range rows {
		d := dateOnly(r.Date)
		if out[r.EmployeeID] == nil {
			out[r.EmployeeID] = map[time.Time]decimal.Decimal{}
		}
		out[r.EmployeeID][d] = out[r.EmployeeID][d].Add(r.Hours)
	}
	return out, nil
}
