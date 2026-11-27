package leave

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavelog"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
)

// UpdateRequestInput is a pending request's new type, dates, half days and reason. A nil Reason
// keeps the one it has.
type UpdateRequestInput struct {
	CategoryID   uuid.UUID
	StartDate    time.Time
	EndDate      time.Time
	StartHalfDay bool
	EndHalfDay   bool
	Reason       *string
	ActingUserID *uuid.UUID
}

// UpdateRequest changes a pending request. own, when set, is the requester's employee id: someone
// else's request answers ErrRequestNotFound. The days are counted again and the balance checked
// without the request's own old days, as a new request would be; the employee does not change.
func (s *Service) UpdateRequest(ctx context.Context, tenantID, id uuid.UUID, own *uuid.UUID, in UpdateRequestInput) (*ent.LeaveRequest, error) {
	current, err := s.orm.LeaveRequest.Query().Where(leaverequest.TenantID(tenantID), leaverequest.ID(id)).Only(ctx)
	if ent.IsNotFound(err) || (err == nil && own != nil && current.EmployeeID != *own) {
		return nil, ErrRequestNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("leave: load request: %w", err)
	}
	if current.Status != leaverequest.StatusPending {
		return nil, ErrNotPendingEdit
	}
	in.StartDate, in.EndDate = utcDay(in.StartDate), utcDay(in.EndDate)
	parts := RequestOptions{StartHalfDay: in.StartHalfDay, EndHalfDay: in.EndHalfDay, Excluding: id}
	count, err := s.PreviewRequestWith(ctx, tenantID, current.EmployeeID, in.CategoryID, in.StartDate, in.EndDate, parts)
	if err != nil {
		return nil, err
	}
	if !count.Days.IsPositive() {
		return nil, ErrNoDays
	}
	// A switched-off type takes no new requests; a request already on it may keep it.
	if count.category != nil && !count.category.IsActive && in.CategoryID != current.CategoryID {
		return nil, ErrInactiveCategory
	}

	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	req, err := tx.LeaveRequest.Query().Where(leaverequest.TenantID(tenantID), leaverequest.ID(id)).ForUpdate().Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: load request: %w", err)
	}
	// Decided while the days were counted.
	if req.Status != leaverequest.StatusPending {
		return nil, ErrNotPendingEdit
	}
	if _, err := tx.Employee.Query().Where(employee.TenantID(tenantID), employee.ID(req.EmployeeID)).
		ForUpdate().Only(ctx); err != nil {
		return nil, fmt.Errorf("leave: lock employee: %w", err)
	}
	if err := refuseOverlap(ctx, tx, tenantID, req.EmployeeID, in.StartDate, in.EndDate, parts); err != nil {
		return nil, err
	}
	chk, err := s.checkBalanceExcluding(ctx, tx.Client(), tenantID, req.EmployeeID, count.category, count.BalanceYear, count.Days, true, id)
	if err != nil {
		return nil, err
	}
	if err := chk.refusal(); err != nil {
		return nil, err
	}
	upd := req.Update().
		SetCategoryID(in.CategoryID).
		SetStartDate(in.StartDate).
		SetEndDate(in.EndDate).
		SetStartHalfDay(in.StartHalfDay).
		SetEndHalfDay(in.EndHalfDay).
		SetDaysRequested(count.Days)
	if in.Reason != nil {
		upd = upd.SetReason(*in.Reason)
	}
	row, err := upd.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: update request: %w", err)
	}
	desc := fmt.Sprintf("leave request changed to %s to %s (%s days)", in.StartDate.Format("2006-01-02"), in.EndDate.Format("2006-01-02"), count.Days)
	logAction(ctx, tx.Client(), tenantID, id, leavelog.ActionUpdate, desc, in.ActingUserID)
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("leave: commit request: %w", err)
	}
	return row.Unwrap(), nil
}
