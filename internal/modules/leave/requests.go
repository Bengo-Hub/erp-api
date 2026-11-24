package leave

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavelog"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
)

// moduleLeaveRequest is the approvals-engine module key for leave requests.
const moduleLeaveRequest = "leave_request"

// DefaultRequestRangeDays bounds a leave request list without dates: requests overlapping the
// year before and the year after today.
const DefaultRequestRangeDays = 365

// RequestFilter narrows a leave request list. From/To select requests overlapping the range.
type RequestFilter struct {
	EmployeeID *uuid.UUID
	Status     string
	From, To   *time.Time
}

// ListRequests returns one page of tenant leave requests, newest first, paged in SQL over a
// bounded date range, with the total.
func (s *Service) ListRequests(ctx context.Context, tenantID uuid.UUID, f RequestFilter, limit, offset int) ([]*ent.LeaveRequest, int, error) {
	now := time.Now().UTC()
	lo := now.AddDate(0, 0, -DefaultRequestRangeDays)
	hi := now.AddDate(0, 0, DefaultRequestRangeDays)
	if f.From != nil {
		lo = *f.From
	}
	if f.To != nil {
		hi = *f.To
	}
	q := s.orm.LeaveRequest.Query().Where(
		leaverequest.TenantID(tenantID),
		leaverequest.EndDateGTE(lo),
		leaverequest.StartDateLT(hi.AddDate(0, 0, 1)),
	)
	if f.EmployeeID != nil {
		q = q.Where(leaverequest.EmployeeID(*f.EmployeeID))
	}
	if f.Status != "" {
		q = q.Where(leaverequest.StatusEQ(leaverequest.Status(f.Status)))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("leave: count requests: %w", err)
	}
	rows, err := q.Order(ent.Desc(leaverequest.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("leave: list requests: %w", err)
	}
	return rows, total, nil
}

// Get fetches one tenant-scoped leave request.
func (s *Service) Get(ctx context.Context, tenantID, id uuid.UUID) (*ent.LeaveRequest, error) {
	return s.orm.LeaveRequest.Query().
		Where(leaverequest.TenantID(tenantID), leaverequest.ID(id)).Only(ctx)
}

// ListLogs returns one page of the tenant-scoped leave audit trail (optionally for one
// request), newest first, with the total. Paged in SQL: the trail only grows.
func (s *Service) ListLogs(ctx context.Context, tenantID uuid.UUID, requestID *uuid.UUID, limit, offset int) ([]*ent.LeaveLog, int, error) {
	q := s.orm.LeaveLog.Query().Where(leavelog.TenantID(tenantID))
	if requestID != nil {
		q = q.Where(leavelog.LeaveRequestID(*requestID))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("leave: count logs: %w", err)
	}
	rows, err := q.Order(ent.Desc(leavelog.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	return rows, total, err
}

// CreateRequestInput is the payload for filing a leave request.
type CreateRequestInput struct {
	EmployeeID   uuid.UUID
	CategoryID   uuid.UUID
	StartDate    time.Time
	EndDate      time.Time
	Reason       string
	ActingUserID *uuid.UUID
}

// CreateRequest files a new pending leave request and writes the create audit log. The server
// counts the days with the leave type's mode. The employee row is locked while the overlap check
// and the insert run, so two requests filed at once cannot cover the same dates.
func (s *Service) CreateRequest(ctx context.Context, tenantID uuid.UUID, in CreateRequestInput) (*ent.LeaveRequest, error) {
	in.StartDate, in.EndDate = utcDay(in.StartDate), utcDay(in.EndDate)
	count, err := s.PreviewRequest(ctx, tenantID, in.EmployeeID, in.CategoryID, in.StartDate, in.EndDate)
	if err != nil {
		return nil, err
	}
	if !count.Days.IsPositive() {
		return nil, ErrNoDays
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.Employee.Query().Where(employee.TenantID(tenantID), employee.ID(in.EmployeeID)).
		ForUpdate().Only(ctx); err != nil {
		return nil, fmt.Errorf("leave: lock employee: %w", err)
	}
	if err := refuseOverlap(ctx, tx, tenantID, in.EmployeeID, in.StartDate, in.EndDate); err != nil {
		return nil, err
	}
	row, err := tx.LeaveRequest.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetCategoryID(in.CategoryID).
		SetStartDate(in.StartDate).
		SetEndDate(in.EndDate).
		SetDaysRequested(count.Days).
		SetReason(in.Reason).
		SetStatus(leaverequest.StatusPending).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: create request: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("leave: commit request: %w", err)
	}
	row = row.Unwrap()
	logAction(ctx, s.orm, tenantID, row.ID, leavelog.ActionCreate, "leave request filed", in.ActingUserID)

	// Sprint 4: if the tenant configured a leave_request approval workflow, open an approval
	// request so the multi-step chain drives the decision. Best-effort; the direct
	// approve/reject path still works when no workflow exists.
	if s.approvals != nil {
		empID := in.EmployeeID
		_, _ = s.approvals.Submit(ctx, tenantID, approvals.SubmitInput{
			Module:              moduleLeaveRequest,
			ObjectID:            row.ID,
			ObjectReference:     "leave:" + row.ID.String(),
			RequesterEmployeeID: &empID,
			SubmittedBy:         in.ActingUserID,
		})
	}
	return row, nil
}

// Approve transitions a pending request to approved, deducts the days from the balance
// (entitled - taken), writes the audit log, and emits the decision notification.
// Rejects invalid transitions (only pending -> approved is allowed).
func (s *Service) Approve(ctx context.Context, tenantID, id uuid.UUID, approverEmployeeID *uuid.UUID, actingUserID *uuid.UUID) (*ent.LeaveRequest, error) {
	// Sprint 4: route through the approvals engine when this leave request has an open
	// approval workflow. Only apply the leave side-effect (status flip + balance deduction)
	// once the multi-step chain is fully approved; intermediate steps just advance the chain.
	if proceed, out, err := s.routeDecision(ctx, tenantID, id, true, "", actingUserID); err != nil {
		return nil, err
	} else if !proceed {
		return out, nil
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	req, err := tx.LeaveRequest.Query().
		Where(leaverequest.TenantID(tenantID), leaverequest.ID(id)).ForUpdate().Only(ctx)
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
	// Sprint 4: route through the approvals engine (a reject is terminal at any step).
	if proceed, out, err := s.routeDecision(ctx, tenantID, id, false, reason, actingUserID); err != nil {
		return nil, err
	} else if !proceed {
		return out, nil
	}
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
	return s.cancel(ctx, tenantID, id, nil, actingUserID)
}

// CancelOwn lets an employee withdraw their own request while it is pending. Someone else's
// request answers ErrRequestNotFound.
func (s *Service) CancelOwn(ctx context.Context, tenantID, id, employeeID uuid.UUID, actingUserID *uuid.UUID) (*ent.LeaveRequest, error) {
	return s.cancel(ctx, tenantID, id, &employeeID, actingUserID)
}

func (s *Service) cancel(ctx context.Context, tenantID, id uuid.UUID, own *uuid.UUID, actingUserID *uuid.UUID) (*ent.LeaveRequest, error) {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	req, err := tx.LeaveRequest.Query().
		Where(leaverequest.TenantID(tenantID), leaverequest.ID(id)).ForUpdate().Only(ctx)
	if ent.IsNotFound(err) || (err == nil && own != nil && req.EmployeeID != *own) {
		return nil, ErrRequestNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("leave: load request: %w", err)
	}
	if own != nil && req.Status != leaverequest.StatusPending {
		return nil, fmt.Errorf("only a pending request can be cancelled; this one is %s, so ask HR", req.Status)
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
	s.withdrawApproval(ctx, tenantID, id)
	return updated, nil
}

// withdrawApproval closes the open approval request of a cancelled leave (best-effort), so it
// leaves the approvers' queue.
func (s *Service) withdrawApproval(ctx context.Context, tenantID, id uuid.UUID) {
	c, ok := s.approvals.(interface {
		Cancel(ctx context.Context, tenantID, requestID uuid.UUID) (*ent.ApprovalRequest, error)
	})
	if !ok {
		return
	}
	if apr, err := s.approvals.FindRequestForObject(ctx, tenantID, moduleLeaveRequest, id); err == nil && apr.Status == "pending" {
		_, _ = c.Cancel(ctx, tenantID, apr.ID)
	}
}

// routeDecision drives the approvals engine for a leave request when one is open.
// Returns proceed=true when the caller should run its own terminal transition:
//   - no approvals engine wired, or no open approval request for this leave  -> proceed=true
//   - approve that fully completes the chain (engine -> approved)             -> proceed=true
//   - reject (terminal at any step)                                          -> proceed=true
//
// Returns proceed=false (with the unchanged leave request) when an intermediate approval
// step was recorded but the chain is not yet complete.
func (s *Service) routeDecision(ctx context.Context, tenantID, id uuid.UUID, approve bool, comment string, actingUserID *uuid.UUID) (bool, *ent.LeaveRequest, error) {
	if s.approvals == nil {
		return true, nil, nil
	}
	apr, err := s.approvals.FindRequestForObject(ctx, tenantID, moduleLeaveRequest, id)
	if ent.IsNotFound(err) {
		return true, nil, nil
	}
	if err != nil {
		return false, nil, fmt.Errorf("leave: find approval request: %w", err)
	}
	if apr.Status != "pending" {
		// Chain already decided elsewhere — fall through to local transition for consistency.
		return true, nil, nil
	}
	dec, err := s.approvals.Decide(ctx, tenantID, approvals.DecisionInput{
		RequestID: apr.ID, Approve: approve, Comment: comment, ActedBy: actingUserID,
	})
	if err != nil {
		return false, nil, fmt.Errorf("leave: approval decision: %w", err)
	}
	if approve && !dec.Finished {
		// Intermediate step approved; leave request stays pending.
		cur, gerr := s.Get(ctx, tenantID, id)
		return false, cur, gerr
	}
	return true, nil, nil
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
