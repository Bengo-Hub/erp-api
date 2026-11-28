package payroll

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalrequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
	"github.com/Bengo-Hub/erp-api/internal/ent/predicate"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
)

// A payroll run (one period, optionally one outlet) is approved through the approvals engine
// before it can be disbursed. A tenant without an active "payroll" workflow still gets a
// request, decided by any holder of the payroll manage permission.
const (
	ModulePayroll               = "payroll"
	payrollFallbackApproverRole = "hrm.payroll.manage"
)

var (
	// ErrApprovalsUnavailable is returned when the approvals engine is not wired.
	ErrApprovalsUnavailable = errors.New("payroll: approvals are not configured")
	// ErrNothingToApprove is returned when the period has no processed, unposted payslips.
	ErrNothingToApprove = errors.New("payroll: no processed payslips awaiting approval for this period")
	// ErrRunPosted is returned when a run that is already posted for payment is sent back.
	ErrRunPosted = errors.New("payroll: this run is already posted for payment; reverse it instead")
)

// ApprovalEngine is the part of the approvals service payroll uses.
type ApprovalEngine interface {
	SubmitWithFallback(ctx context.Context, tenantID uuid.UUID, in approvals.SubmitInput, fallbackRole string) (*ent.ApprovalRequest, error)
	FindRequestForObject(ctx context.Context, tenantID uuid.UUID, module string, objectID uuid.UUID) (*ent.ApprovalRequest, error)
	Cancel(ctx context.Context, tenantID, requestID uuid.UUID) (*ent.ApprovalRequest, error)
	RegisterHook(module string, h approvals.Hook)
}

// SetApprovals wires the approvals engine and registers the hook that applies a run decision.
func (s *Service) SetApprovals(a ApprovalEngine) {
	s.approvals = a
	if a != nil {
		a.RegisterHook(ModulePayroll, s.applyRunDecision)
	}
}

// RunApprovalObjectID is the approvals object id of a payroll run (period + outlet scope).
func RunApprovalObjectID(tenantID uuid.UUID, period time.Time, outletID uuid.UUID) uuid.UUID {
	return uuid.NewSHA1(tenantID, []byte("payroll_run_approval|"+buildBatchRef(tenantID, period, outletID)))
}

// runScope selects the run's payslips that are processed and not yet posted for payment. A
// posted payslip is approved and tagged with its batch ref.
func runScope(tenantID uuid.UUID, period time.Time, outletID uuid.UUID) []predicate.Payslip {
	ps := []predicate.Payslip{
		payslip.TenantID(tenantID),
		payslip.PaymentPeriod(period),
		payslip.DeleteStatus(false),
		payslip.PayrollStatus("complete"),
		payslip.Published(false),
		payslip.Not(payslip.And(payslip.ApprovalStatus("approved"), payslip.BatchRefNotNil())),
	}
	if outletID != uuid.Nil {
		ps = append(ps, payslip.OutletID(outletID))
	}
	return ps
}

// RunApproval is the approval state of a run returned to the caller.
type RunApproval struct {
	Status    string     `json:"approval_status"` // pending | approved
	RequestID *uuid.UUID `json:"approval_request_id,omitempty"`
	Count     int        `json:"count"`
}

// SubmitRunForApproval puts the run's processed payslips up for approval. It is idempotent: a
// run with a pending request returns that request, and a fully approved run returns approved.
func (s *Service) SubmitRunForApproval(ctx context.Context, tenantID uuid.UUID, period time.Time, outletID uuid.UUID, submittedBy *uuid.UUID) (RunApproval, error) {
	if s.approvals == nil {
		return RunApproval{}, ErrApprovalsUnavailable
	}
	scope := runScope(tenantID, period, outletID)
	total, err := s.orm.Payslip.Query().Where(scope...).Count(ctx)
	if err != nil {
		return RunApproval{}, fmt.Errorf("payroll: count run payslips: %w", err)
	}
	if total == 0 {
		return RunApproval{}, ErrNothingToApprove
	}
	objectID := RunApprovalObjectID(tenantID, period, outletID)
	latest, err := s.approvals.FindRequestForObject(ctx, tenantID, ModulePayroll, objectID)
	if err != nil && !ent.IsNotFound(err) {
		return RunApproval{}, fmt.Errorf("payroll: load run approval: %w", err)
	}
	if latest != nil && latest.Status == approvalrequest.StatusPending {
		return RunApproval{Status: "pending", RequestID: &latest.ID, Count: total}, nil
	}
	open, err := s.orm.Payslip.Query().Where(scope...).Where(payslip.ApprovalStatusNEQ("approved")).Count(ctx)
	if err != nil {
		return RunApproval{}, fmt.Errorf("payroll: count unapproved payslips: %w", err)
	}
	if open == 0 {
		ra := RunApproval{Status: "approved", Count: total}
		if latest != nil {
			ra.RequestID = &latest.ID
		}
		return ra, nil
	}
	// Everything in the run goes up together, so an approver signs off the whole run.
	// A batch tag left from an earlier, reversed posting is cleared so only a new posting tags it.
	if _, err := s.orm.Payslip.Update().Where(scope...).SetApprovalStatus("pending").ClearBatchRef().Save(ctx); err != nil {
		return RunApproval{}, fmt.Errorf("payroll: mark run pending: %w", err)
	}
	ref := "Payroll " + period.Format("Jan 2006")
	if outletID != uuid.Nil {
		ref += " (outlet " + outletID.String()[:8] + ")"
	}
	req, err := s.approvals.SubmitWithFallback(ctx, tenantID, approvals.SubmitInput{
		Module: ModulePayroll, ObjectID: objectID,
		ObjectReference: fmt.Sprintf("%s, %d payslips", ref, total),
		SubmittedBy:     submittedBy,
	}, payrollFallbackApproverRole)
	if err != nil {
		return RunApproval{}, fmt.Errorf("payroll: submit run for approval: %w", err)
	}
	return RunApproval{Status: "pending", RequestID: &req.ID, Count: total}, nil
}

// RejectRun sends an unposted run back for correction: its payslips become rejected and a
// pending approval request is cancelled. A run already posted for payment must be reversed.
func (s *Service) RejectRun(ctx context.Context, tenantID uuid.UUID, period time.Time, outletID uuid.UUID) (int, error) {
	posted := []predicate.Payslip{
		payslip.TenantID(tenantID), payslip.PaymentPeriod(period), payslip.DeleteStatus(false),
		payslip.BatchRefNotNil(), payslip.ApprovalStatus("approved"),
	}
	if outletID != uuid.Nil {
		posted = append(posted, payslip.OutletID(outletID))
	}
	if n, err := s.orm.Payslip.Query().Where(posted...).Count(ctx); err != nil {
		return 0, fmt.Errorf("payroll: check posted run: %w", err)
	} else if n > 0 {
		return 0, ErrRunPosted
	}
	if s.approvals != nil {
		latest, err := s.approvals.FindRequestForObject(ctx, tenantID, ModulePayroll, RunApprovalObjectID(tenantID, period, outletID))
		if err != nil && !ent.IsNotFound(err) {
			return 0, fmt.Errorf("payroll: load run approval: %w", err)
		}
		if latest != nil && latest.Status == approvalrequest.StatusPending {
			if _, err := s.approvals.Cancel(ctx, tenantID, latest.ID); err != nil {
				return 0, fmt.Errorf("payroll: cancel run approval: %w", err)
			}
		}
	}
	return s.orm.Payslip.Update().Where(runScope(tenantID, period, outletID)...).SetApprovalStatus("rejected").Save(ctx)
}

// applyRunDecision is the approvals hook: it moves the run's pending payslips to approved or
// rejected. The request's object id is derived from the run scope, so the hook finds the run by
// recomputing that id for each period and outlet that has pending payslips. Idempotent: once the
// payslips have left pending there is nothing to change.
func (s *Service) applyRunDecision(ctx context.Context, tenantID uuid.UUID, req *ent.ApprovalRequest) error {
	var groups []struct {
		PaymentPeriod *time.Time `json:"payment_period"`
		OutletID      *uuid.UUID `json:"outlet_id"`
	}
	if err := s.orm.Payslip.Query().
		Where(payslip.TenantID(tenantID), payslip.ApprovalStatus("pending"), payslip.DeleteStatus(false), payslip.Published(false)).
		GroupBy(payslip.FieldPaymentPeriod, payslip.FieldOutletID).
		Scan(ctx, &groups); err != nil {
		return fmt.Errorf("load pending payroll runs: %w", err)
	}
	status := "rejected"
	if req.Status == approvalrequest.StatusApproved {
		status = "approved"
	}
	for _, g := range groups {
		if g.PaymentPeriod == nil {
			continue
		}
		period := g.PaymentPeriod.UTC()
		candidates := []uuid.UUID{uuid.Nil}
		if g.OutletID != nil {
			candidates = append(candidates, *g.OutletID)
		}
		for _, outlet := range candidates {
			if RunApprovalObjectID(tenantID, period, outlet) != req.ObjectID {
				continue
			}
			_, err := s.orm.Payslip.Update().
				Where(runScope(tenantID, period, outlet)...).
				Where(payslip.ApprovalStatus("pending")).
				SetApprovalStatus(status).Save(ctx)
			if err != nil {
				return fmt.Errorf("apply payroll run decision: %w", err)
			}
			return nil
		}
	}
	return nil
}

// RunStatus is the state of a payroll run shown on the process page: where it is in
// process, approve, disburse, and what the operator may do next.
type RunStatus struct {
	Period            string     `json:"payment_period"`
	Payslips          int        `json:"payslips"`
	Draft             int        `json:"draft"`
	Pending           int        `json:"pending"`
	Approved          int        `json:"approved"`
	Rejected          int        `json:"rejected"`
	Posted            int        `json:"posted"`
	Paid              int        `json:"paid"`
	ApprovalRequestID *uuid.UUID `json:"approval_request_id,omitempty"`
	RequestStatus     string     `json:"approval_request_status,omitempty"`
	CanSubmit         bool       `json:"can_submit"`
	CanDisburse       bool       `json:"can_disburse"`
	CanReverse        bool       `json:"can_reverse"`
	// Shortfalls lists what the run could not deduct: recoveries the deduction limits deferred to
	// later months (kind "deferred", the balance keeps them) and assigned deductions net pay or
	// the limit could not cover (kind "not_deducted").
	Shortfalls    []RunShortfall `json:"shortfalls"`
	DeferredTotal string         `json:"deferred_total"`
}

// RunShortfall is one payslip's deferred recovery or deduction not taken.
type RunShortfall struct {
	EmployeeID   uuid.UUID `json:"employee_id"`
	EmployeeName string    `json:"employee_name"`
	Kind         string    `json:"kind"` // deferred | not_deducted
	Code         string    `json:"code"`
	Label        string    `json:"label"`
	Amount       string    `json:"amount"`
}

// recoveryCodes (gl_breakdown.go) lists the recoverables, which are the deferred kind here.

// runShortfalls reads the informational shortfall lines of a run's payslips.
func (s *Service) runShortfalls(ctx context.Context, tenantID uuid.UUID, rows []*ent.Payslip) ([]RunShortfall, decimal.Decimal, error) {
	out := []RunShortfall{}
	total := decimal.Zero
	if len(rows) == 0 {
		return out, total, nil
	}
	emp := make(map[uuid.UUID]uuid.UUID, len(rows))
	ids := make([]uuid.UUID, 0, len(rows))
	for _, r := range rows {
		emp[r.ID] = r.EmployeeID
		ids = append(ids, r.ID)
	}
	lines, err := s.orm.PayslipLine.Query().Where(payslipline.TenantID(tenantID), payslipline.PayslipIDIn(ids...),
		payslipline.Section(secShortfall)).Order(ent.Asc(payslipline.FieldSortOrder)).All(ctx)
	if err != nil {
		return nil, total, fmt.Errorf("payroll: run shortfalls: %w", err)
	}
	names := map[uuid.UUID]string{}
	for _, l := range lines {
		eid := emp[l.PayslipID]
		if _, ok := names[eid]; !ok {
			names[eid], _ = s.EmployeeLabel(ctx, tenantID, eid)
		}
		kind := "not_deducted"
		if recoveryCodes[l.Code] {
			kind = "deferred"
			total = total.Add(l.CashAmount)
		}
		out = append(out, RunShortfall{EmployeeID: eid, EmployeeName: names[eid], Kind: kind, Code: l.Code,
			Label: l.Label, Amount: l.CashAmount.StringFixed(2)})
	}
	return out, total, nil
}

// GetRunStatus summarises a run's payslips by approval and payment state.
func (s *Service) GetRunStatus(ctx context.Context, tenantID uuid.UUID, period time.Time, outletID uuid.UUID) (RunStatus, error) {
	q := s.orm.Payslip.Query().Where(payslip.TenantID(tenantID), payslip.PaymentPeriod(period),
		payslip.DeleteStatus(false), payslip.PayrollStatus("complete"))
	if outletID != uuid.Nil {
		q = q.Where(payslip.OutletID(outletID))
	}
	rows, err := q.Select(payslip.FieldID, payslip.FieldEmployeeID, payslip.FieldApprovalStatus, payslip.FieldPublished, payslip.FieldBatchRef).All(ctx)
	if err != nil {
		return RunStatus{}, fmt.Errorf("payroll: run status: %w", err)
	}
	st := RunStatus{Period: period.Format("2006-01"), Payslips: len(rows)}
	short, deferred, err := s.runShortfalls(ctx, tenantID, rows)
	if err != nil {
		return RunStatus{}, err
	}
	st.Shortfalls, st.DeferredTotal = short, deferred.StringFixed(2)
	for _, r := range rows {
		posted := r.BatchRef != nil && r.ApprovalStatus == "approved"
		switch {
		case r.Published:
			st.Paid++
		case posted:
			st.Posted++
		}
		if r.Published || posted {
			continue
		}
		switch r.ApprovalStatus {
		case "approved":
			st.Approved++
		case "pending":
			st.Pending++
		case "rejected":
			st.Rejected++
		default:
			st.Draft++
		}
	}
	if s.approvals != nil {
		if req, err := s.approvals.FindRequestForObject(ctx, tenantID, ModulePayroll, RunApprovalObjectID(tenantID, period, outletID)); err == nil && req != nil {
			st.ApprovalRequestID, st.RequestStatus = &req.ID, string(req.Status)
		}
	}
	st.CanSubmit = st.Draft+st.Rejected > 0
	// Disburse posts newly approved payslips, or retries a posted batch that is not fully paid.
	st.CanDisburse = st.Approved > 0 || st.Posted > 0
	// Only a posted batch with nothing paid yet can be reversed.
	st.CanReverse = st.Posted > 0 && st.Paid == 0
	return st, nil
}
