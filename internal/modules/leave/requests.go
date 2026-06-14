package leave

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavelog"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
)

// ListRequests returns leave requests filtered by tenant (+ optional employee/status).
func (s *Service) ListRequests(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, status string) ([]*ent.LeaveRequest, error) {
	q := s.orm.LeaveRequest.Query().Where(leaverequest.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(leaverequest.EmployeeID(*employeeID))
	}
	if status != "" {
		q = q.Where(leaverequest.StatusEQ(leaverequest.Status(status)))
	}
	return q.Order(ent.Desc(leaverequest.FieldCreatedAt)).All(ctx)
}

// Get fetches one tenant-scoped leave request.
func (s *Service) Get(ctx context.Context, tenantID, id uuid.UUID) (*ent.LeaveRequest, error) {
	return s.orm.LeaveRequest.Query().
		Where(leaverequest.TenantID(tenantID), leaverequest.ID(id)).Only(ctx)
}

// CreateRequestInput is the payload for filing a leave request.
type CreateRequestInput struct {
	EmployeeID    uuid.UUID
	CategoryID    uuid.UUID
	StartDate     time.Time
	EndDate       time.Time
	DaysRequested decimal.Decimal
	Reason        string
	ActingUserID  *uuid.UUID
}

// CreateRequest files a new pending leave request and writes the create audit log.
func (s *Service) CreateRequest(ctx context.Context, tenantID uuid.UUID, in CreateRequestInput) (*ent.LeaveRequest, error) {
	if in.EndDate.Before(in.StartDate) {
		return nil, fmt.Errorf("leave: end_date before start_date")
	}
	if in.DaysRequested.LessThanOrEqual(decimal.Zero) {
		return nil, fmt.Errorf("leave: days_requested must be > 0")
	}
	row, err := s.orm.LeaveRequest.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetCategoryID(in.CategoryID).
		SetStartDate(in.StartDate).
		SetEndDate(in.EndDate).
		SetDaysRequested(in.DaysRequested).
		SetReason(in.Reason).
		SetStatus(leaverequest.StatusPending).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: create request: %w", err)
	}
	logAction(ctx, s.orm, tenantID, row.ID, leavelog.ActionCreate, "leave request filed", in.ActingUserID)
	return row, nil
}

// Approve transitions a pending request to approved, deducts the days from the balance
// (entitled - taken), writes the audit log, and emits the decision notification.
// Rejects invalid transitions (only pending -> approved is allowed).
func (s *Service) Approve(ctx context.Context, tenantID, id uuid.UUID, approverEmployeeID *uuid.UUID, actingUserID *uuid.UUID) (*ent.LeaveRequest, error) {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	req, err := tx.LeaveRequest.Query().
		Where(leaverequest.TenantID(tenantID), leaverequest.ID(id)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: load request: %w", err)
	}
	if req.Status != leaverequest.StatusPending {
		return nil, fmt.Errorf("leave: cannot approve a %s request", req.Status)
	}

	upd := req.Update().SetStatus(leaverequest.StatusApproved).SetApprovedAt(time.Now().UTC())
	if approverEmployeeID != nil {
		upd = upd.SetApprovedBy(*approverEmployeeID)
	}
	updated, err := upd.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: approve update: %w", err)
	}

	// Deduct from the balance for the start-date year (taken += days; remaining recomputed).
	year := req.StartDate.Year()
	if err := applyTakenTx(ctx, tx, tenantID, req.EmployeeID, req.CategoryID, year, req.DaysRequested); err != nil {
		return nil, err
	}

	logAction(ctx, tx.Client(), tenantID, id, leavelog.ActionApprove, "leave request approved", actingUserID)
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("leave: commit approve: %w", err)
	}
	s.emitDecision(ctx, tenantID, updated)
	return updated, nil
}

// Reject transitions a pending request to rejected with a reason and emits notification.
func (s *Service) Reject(ctx context.Context, tenantID, id uuid.UUID, reason string, actingUserID *uuid.UUID) (*ent.LeaveRequest, error) {
	req, err := s.Get(ctx, tenantID, id)
	if err != nil {
		return nil, fmt.Errorf("leave: load request: %w", err)
	}
	if req.Status != leaverequest.StatusPending {
		return nil, fmt.Errorf("leave: cannot reject a %s request", req.Status)
	}
	updated, err := req.Update().
		SetStatus(leaverequest.StatusRejected).
		SetRejectionReason(reason).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: reject update: %w", err)
	}
	logAction(ctx, s.orm, tenantID, id, leavelog.ActionReject, "leave request rejected: "+reason, actingUserID)
	s.emitDecision(ctx, tenantID, updated)
	return updated, nil
}

// Cancel transitions a pending/approved request to cancelled. If it was approved, the
// previously-deducted days are returned to the balance.
func (s *Service) Cancel(ctx context.Context, tenantID, id uuid.UUID, actingUserID *uuid.UUID) (*ent.LeaveRequest, error) {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	req, err := tx.LeaveRequest.Query().
		Where(leaverequest.TenantID(tenantID), leaverequest.ID(id)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: load request: %w", err)
	}
	if req.Status == leaverequest.StatusCancelled || req.Status == leaverequest.StatusRejected {
		return nil, fmt.Errorf("leave: cannot cancel a %s request", req.Status)
	}
	wasApproved := req.Status == leaverequest.StatusApproved
	updated, err := req.Update().SetStatus(leaverequest.StatusCancelled).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: cancel update: %w", err)
	}
	if wasApproved {
		year := req.StartDate.Year()
		if err := applyTakenTx(ctx, tx, tenantID, req.EmployeeID, req.CategoryID, year, req.DaysRequested.Neg()); err != nil {
			return nil, err
		}
	}
	logAction(ctx, tx.Client(), tenantID, id, leavelog.ActionCancel, "leave request cancelled", actingUserID)
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("leave: commit cancel: %w", err)
	}
	return updated, nil
}

// applyTakenTx adjusts days_taken by delta (positive = consume, negative = return) and
// recomputes days_remaining = entitled - taken. Creates a zero-entitled balance if none.
func applyTakenTx(ctx context.Context, tx *ent.Tx, tenantID, employeeID, categoryID uuid.UUID, year int, delta decimal.Decimal) error {
	bal, err := tx.LeaveBalance.Query().Where(
		leavebalance.TenantID(tenantID),
		leavebalance.EmployeeID(employeeID),
		leavebalance.CategoryID(categoryID),
		leavebalance.Year(year),
	).First(ctx)
	if ent.IsNotFound(err) {
		taken := delta
		if taken.LessThan(decimal.Zero) {
			taken = decimal.Zero
		}
		_, cerr := tx.LeaveBalance.Create().
			SetTenantID(tenantID).SetEmployeeID(employeeID).SetCategoryID(categoryID).
			SetYear(year).SetDaysEntitled(decimal.Zero).SetDaysTaken(taken).
			SetDaysRemaining(taken.Neg()).Save(ctx)
		if cerr != nil {
			return fmt.Errorf("leave: create balance on take: %w", cerr)
		}
		return nil
	}
	if err != nil {
		return fmt.Errorf("leave: balance lookup on take: %w", err)
	}
	taken := bal.DaysTaken.Add(delta)
	if taken.LessThan(decimal.Zero) {
		taken = decimal.Zero
	}
	remaining := bal.DaysEntitled.Sub(taken)
	if _, uerr := bal.Update().SetDaysTaken(taken).SetDaysRemaining(remaining).Save(ctx); uerr != nil {
		return fmt.Errorf("leave: update balance on take: %w", uerr)
	}
	return nil
}

// emitDecision publishes the leave-decision notification (best-effort; logged not fatal).
func (s *Service) emitDecision(ctx context.Context, tenantID uuid.UUID, req *ent.LeaveRequest) {
	if s.notify == nil {
		return
	}
	_ = s.notify.NotifyLeaveDecision(ctx, tenantID, req)
}
