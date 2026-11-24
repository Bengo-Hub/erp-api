package payroll

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/idempotencykey"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

// Idempotency scopes. A posting row is written in the same transaction as the GL event, and
// its unique key stops two requests from posting the same batch cycle. A reversal row closes a
// cycle, so the number of reversal rows for a batch is the current cycle.
const (
	scopeDisburse = "payroll.disburse"
	scopeReverse  = "payroll.reverse"
)

var (
	// ErrRunNotApproved is returned when the period has processed payslips but none approved.
	ErrRunNotApproved = errors.New("payroll: the run is not approved yet; submit it for approval and disburse once it is approved")
	// ErrNothingToReverse is returned when no batch is posted for the period.
	ErrNothingToReverse = errors.New("payroll: no posted batch to reverse for this period")
	// ErrBatchPaid is returned when net pay already went out for part of the batch.
	ErrBatchPaid = errors.New("payroll: net pay has already been sent for this batch, so it cannot be reversed; correct it in the next run")
	// ErrPostingInProgress is returned when another request is posting the same batch.
	ErrPostingInProgress = errors.New("payroll: this batch is being posted by another request; try again shortly")
)

// payoutSender sends a payout batch to treasury (the treasury S2S client).
type payoutSender interface {
	DisburseBatch(ctx context.Context, tenantID uuid.UUID, payouts []treasury.Payout, idempotencyKey string) (treasury.BatchResult, error)
}

// Disburser posts an approved payroll batch (erp.payroll.processed, atomically with the payroll
// changes) and pays net pay through treasury. Posting happens once per batch cycle; paying can
// be retried any number of times and only payslips treasury dispatched are marked paid.
type Disburser struct {
	orm       *ent.Client
	publisher *events.Publisher
	treasury  payoutSender
	log       *zap.Logger
}

func NewDisburser(orm *ent.Client, publisher *events.Publisher, treasuryClient *treasury.Client, log *zap.Logger) *Disburser {
	d := &Disburser{orm: orm, publisher: publisher, log: log.Named("payroll.disburse")}
	if treasuryClient != nil {
		d.treasury = treasuryClient
	}
	return d
}

// DisburseParams selects the batch to disburse.
type DisburseParams struct {
	TenantID   uuid.UUID
	OutletID   uuid.UUID // uuid.Nil = all outlets
	Period     time.Time
	PayslipIDs []uuid.UUID // optional explicit selection
}

// DisburseResult summarises the outcome.
type DisburseResult struct {
	BatchRef        string          `json:"batch_ref"`
	Published       bool            `json:"published"` // the GL event is posted (now or earlier)
	Disbursed       bool            `json:"disbursed"` // every payslip in the batch is paid
	Count           int             `json:"count"`
	Paid            int             `json:"paid"`
	NetTotal        decimal.Decimal `json:"net_total"`
	DisburseError   string          `json:"disburse_error,omitempty"`
	AlreadyDone     bool            `json:"already_done,omitempty"`
	PendingApproval bool            `json:"pending_approval,omitempty"` // treasury requires finance approval (+OTP) first
}

// cycleRef is the batch reference of one posting cycle. Treasury books erp.payroll.processed
// once per batch_ref, so a batch posted again after a reversal needs a new reference.
func cycleRef(batchRef string, cycle int) string {
	if cycle == 0 {
		return batchRef
	}
	return fmt.Sprintf("%s-r%d", batchRef, cycle)
}

func cycleKey(scope, batchRef string, cycle int) string {
	return fmt.Sprintf("%s|%s|%d", scope, batchRef, cycle)
}

// batchCycle is the number of times the batch has been reversed.
func (d *Disburser) batchCycle(ctx context.Context, batchRef string) (int, error) {
	n, err := d.orm.IdempotencyKey.Query().
		Where(idempotencykey.Scope(scopeReverse), idempotencykey.KeyHasPrefix(scopeReverse+"|"+batchRef+"|")).
		Count(ctx)
	if err != nil {
		return 0, fmt.Errorf("payroll: batch cycle: %w", err)
	}
	return n, nil
}

// postedSlips are the payslips posted in the current cycle (approved and tagged with its ref).
func (d *Disburser) postedSlips(ctx context.Context, tenantID uuid.UUID, ref string) ([]*ent.Payslip, error) {
	rows, err := d.orm.Payslip.Query().Where(
		payslip.TenantID(tenantID),
		payslip.BatchRef(ref),
		payslip.ApprovalStatus("approved"),
		payslip.DeleteStatus(false),
	).Order(ent.Asc(payslip.FieldID)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("payroll: load posted batch: %w", err)
	}
	return rows, nil
}

// Disburse posts the approved run (once per cycle) and then asks treasury to pay every payslip
// of the posted batch that is not paid yet. It is safe to call again at any point:
//   - a batch already posted is not posted twice (the posting row's unique key and the
//     payslips' batch tag both guard it);
//   - every call re-sends the same payouts under the same Idempotency-Key, and treasury refuses
//     a second payout for a reference it already holds, so a retry pays only what is unpaid;
//   - a payslip is marked paid only when treasury reports its payout dispatched.
//
// A run that is not approved is never posted or paid.
func (d *Disburser) Disburse(ctx context.Context, p DisburseParams) (DisburseResult, error) {
	batchRef := buildBatchRef(p.TenantID, p.Period, p.OutletID)
	cycle, err := d.batchCycle(ctx, batchRef)
	if err != nil {
		return DisburseResult{}, err
	}
	ref := cycleRef(batchRef, cycle)
	res := DisburseResult{BatchRef: ref}

	slips, err := d.postedSlips(ctx, p.TenantID, ref)
	if err != nil {
		return res, err
	}
	if len(slips) == 0 {
		slips, err = d.post(ctx, p, batchRef, cycle)
		if errors.Is(err, errAlreadyPosted) {
			// Another request posted this cycle first; carry on to the payout step with its batch.
			if slips, err = d.postedSlips(ctx, p.TenantID, ref); err == nil && len(slips) == 0 {
				err = ErrPostingInProgress
			}
		}
		if err != nil {
			return res, err
		}
		if len(slips) == 0 {
			return res, nil
		}
	}
	res.Published = true
	res.Count = len(slips)
	unpaid := 0
	for _, s := range slips {
		res.NetTotal = res.NetTotal.Add(s.NetPay)
		if s.Published {
			res.Paid++
		} else {
			unpaid++
		}
	}
	if unpaid == 0 {
		res.Disbursed, res.AlreadyDone = true, true
		return res, nil
	}
	return d.pay(ctx, p, batchRef, ref, slips, res)
}

var errAlreadyPosted = errors.New("payroll: batch cycle already posted")

// post writes the GL event, the batch tag, the recoverable write-back and the posting row in
// one transaction. It returns the posted payslips, or none when nothing is approved.
func (d *Disburser) post(ctx context.Context, p DisburseParams, batchRef string, cycle int) ([]*ent.Payslip, error) {
	ref := cycleRef(batchRef, cycle)
	slips, err := d.selectPayslips(ctx, p)
	if err != nil {
		return nil, err
	}
	if len(slips) == 0 {
		waiting, err := d.orm.Payslip.Query().Where(runScope(p.TenantID, p.Period, p.OutletID)...).
			Where(payslip.ApprovalStatusNEQ("approved")).Exist(ctx)
		if err != nil {
			return nil, fmt.Errorf("disburse: check approval: %w", err)
		}
		if waiting {
			return nil, ErrRunNotApproved
		}
		return nil, nil
	}
	empByID, err := d.loadEmployees(ctx, p.TenantID, slips)
	if err != nil {
		return nil, err
	}
	prefs := d.loadPayoutPrefs(ctx, p.TenantID, slips)
	payload, _ := buildPayrollEvent(slips, empByID, prefs, p, ref)
	// Attribute the gross to projects and department cost centers for treasury budgets.
	if shares, aerr := d.buildCostAllocations(ctx, p.TenantID, p.Period, slips); aerr == nil {
		payload["allocations"] = allocationsPayload(shares)
	}

	tx, err := d.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("disburse: begin tx: %w", err)
	}
	committed := false
	defer func() {
		if !committed {
			_ = tx.Rollback()
		}
	}()
	// The posting row goes first: its unique key makes a concurrent second post fail here,
	// before any event is written.
	if _, err := tx.IdempotencyKey.Create().
		SetKey(cycleKey(scopeDisburse, batchRef, cycle)).
		SetScope(scopeDisburse).
		SetTenantID(p.TenantID).
		SetStatus("processing").
		Save(ctx); err != nil {
		if ent.IsConstraintError(err) {
			return nil, errAlreadyPosted
		}
		return nil, fmt.Errorf("disburse: posting row: %w", err)
	}
	txPub := events.NewPublisher(tx.Client(), "erp")
	if err := txPub.Publish(ctx, p.TenantID, events.AggregateUUID(p.TenantID, ref), "payroll.processed", payload); err != nil {
		return nil, fmt.Errorf("disburse: publish: %w", err)
	}
	ids := make([]uuid.UUID, len(slips))
	for i, s := range slips {
		ids[i] = s.ID
	}
	if _, err := tx.Payslip.Update().Where(payslip.IDIn(ids...)).SetBatchRef(ref).Save(ctx); err != nil {
		return nil, fmt.Errorf("disburse: tag batch: %w", err)
	}
	// Persist repayment write-back for every recoverable this batch recovered (loans/advances/
	// loss-damages/staff-purchases), atomically with the GL event + batch tag. For
	// staff purchases, publish erp.staff_purchase.recovered in the SAME tx so POS pays down the
	// linked layaway/credit balance.
	settlements, err := applyRecoveries(ctx, tx, p.TenantID, ids, ref)
	if err != nil {
		return nil, fmt.Errorf("disburse: apply recoveries: %w", err)
	}
	for _, st := range settlements {
		if err := txPub.Publish(ctx, p.TenantID, st.PurchaseID, "staff_purchase.recovered", map[string]any{
			"staff_purchase_id":      st.PurchaseID.String(),
			"source_key":             st.SourceKey,
			"origin":                 st.Origin,
			"pos_reference":          st.POSReference,
			"amount_recovered":       st.AmountRecovered.StringFixed(2),
			"amount_recovered_total": st.AmountRecoveredTotal.StringFixed(2),
			"outstanding":            st.Outstanding.StringFixed(2),
			"settled":                st.Settled,
			"batch_ref":              ref,
			"period":                 p.Period.Format("2006-01-02"),
		}); err != nil {
			return nil, fmt.Errorf("disburse: publish staff_purchase.recovered: %w", err)
		}
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("disburse: commit: %w", err)
	}
	committed = true
	ref2 := ref
	for _, s := range slips {
		s.BatchRef = &ref2
	}
	return slips, nil
}

// pay sends the whole posted batch to treasury and marks the payslips treasury dispatched as
// paid. The batch is always sent whole, so treasury's finance approval (bound to the key and
// the exact items) stays the same across retries; items already paid come back as dispatched
// without a second payment.
func (d *Disburser) pay(ctx context.Context, p DisburseParams, batchRef, ref string, slips []*ent.Payslip, res DisburseResult) (DisburseResult, error) {
	if d.treasury == nil {
		res.DisburseError = treasury.ErrNotConfigured.Error()
		return res, nil
	}
	empByID, err := d.loadEmployees(ctx, p.TenantID, slips)
	if err != nil {
		return res, err
	}
	prefs := d.loadPayoutPrefs(ctx, p.TenantID, slips)
	payload, _ := buildPayrollEvent(slips, empByID, prefs, p, ref)
	payouts, refToSlip := buildPayouts(payload, batchRef, p.Period)

	done := map[uuid.UUID]bool{}
	// A payslip with no net pay has nothing to send and counts as paid.
	for _, s := range slips {
		if !s.NetPay.IsPositive() {
			done[s.ID] = true
		}
	}
	result, err := d.treasury.DisburseBatch(ctx, p.TenantID, payouts, ref)
	switch {
	case errors.Is(err, treasury.ErrApprovalPending):
		// Treasury opened a finance approval for this batch. Nothing was paid; disbursing again
		// after sign-off sends the same batch under the same key.
		res.PendingApproval = true
		res.DisburseError = "pending finance approval"
		d.log.Info("payroll disbursement pending finance approval in treasury", zap.String("batch", ref))
	case err != nil:
		res.DisburseError = err.Error()
		d.log.Warn("treasury disburse failed (GL event already posted)", zap.String("batch", ref), zap.Error(err))
	default:
		for r := range result.DispatchedRefs() {
			if id, ok := refToSlip[r]; ok {
				done[id] = true
			}
		}
		var failed []string
		for _, it := range result.Results {
			if it.Status != "dispatched" {
				failed = append(failed, strings.TrimSpace(it.Reference+" "+it.Error))
			}
		}
		if len(failed) > 0 {
			res.DisburseError = fmt.Sprintf("%d payout(s) not dispatched: %s", len(failed), strings.Join(failed, "; "))
		}
	}

	var newlyPaid []uuid.UUID
	for _, s := range slips {
		if !s.Published && done[s.ID] {
			newlyPaid = append(newlyPaid, s.ID)
		}
	}
	if len(newlyPaid) > 0 {
		if err := d.markPaid(ctx, p.TenantID, newlyPaid); err != nil {
			// The money moved; the next disburse sees treasury's existing payouts and marks them.
			d.log.Error("payouts dispatched but payslips not marked paid", zap.String("batch", ref), zap.Error(err))
			res.DisburseError = "payouts sent but not recorded; disburse again to record them"
			return res, nil
		}
	}
	res.Paid += len(newlyPaid)
	res.Disbursed = res.Paid == res.Count
	if res.Disbursed {
		cycle, _ := d.batchCycle(ctx, batchRef)
		if _, err := d.orm.IdempotencyKey.Update().
			Where(idempotencykey.Key(cycleKey(scopeDisburse, batchRef, cycle)), idempotencykey.Scope(scopeDisburse)).
			SetStatus("processed").Save(ctx); err != nil {
			d.log.Warn("posting row not closed", zap.String("batch", ref), zap.Error(err))
		}
	}
	return res, nil
}

// markPaid records payslips as paid and settles the expense claims they reimbursed, in one
// transaction.
func (d *Disburser) markPaid(ctx context.Context, tenantID uuid.UUID, ids []uuid.UUID) error {
	tx, err := d.orm.Tx(ctx)
	if err != nil {
		return err
	}
	if _, err := tx.Payslip.Update().Where(payslip.TenantID(tenantID), payslip.IDIn(ids...)).
		SetPublished(true).Save(ctx); err != nil {
		_ = tx.Rollback()
		return err
	}
	if err := markClaimsPaid(ctx, tx.Client(), tenantID, ids); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}

// Reverse reverses a posted batch that has not been paid: it publishes erp.payroll.reversed
// (treasury posts the inverse GL journal), sends the payslips back to rejected and untags them
// so they can be corrected, approved and posted again in a new cycle, and undoes the
// recoverable write-back. A batch with any paid payslip is refused, because its money has left.
// Idempotent per cycle through the reversal row's unique key.
func (d *Disburser) Reverse(ctx context.Context, p DisburseParams) (DisburseResult, error) {
	batchRef := buildBatchRef(p.TenantID, p.Period, p.OutletID)
	cycle, err := d.batchCycle(ctx, batchRef)
	if err != nil {
		return DisburseResult{}, err
	}
	ref := cycleRef(batchRef, cycle)
	slips, err := d.postedSlips(ctx, p.TenantID, ref)
	if err != nil {
		return DisburseResult{}, err
	}
	if len(slips) == 0 {
		return DisburseResult{BatchRef: ref}, ErrNothingToReverse
	}
	for _, s := range slips {
		if s.Published {
			return DisburseResult{BatchRef: ref}, ErrBatchPaid
		}
	}
	empByID, err := d.loadEmployees(ctx, p.TenantID, slips)
	if err != nil {
		return DisburseResult{}, err
	}
	prefs := d.loadPayoutPrefs(ctx, p.TenantID, slips)
	payload, netTotal := buildPayrollEvent(slips, empByID, prefs, p, ref)
	// Attribute the gross to projects and department cost centers for treasury budgets.
	if shares, aerr := d.buildCostAllocations(ctx, p.TenantID, p.Period, slips); aerr == nil {
		payload["allocations"] = allocationsPayload(shares)
	}

	tx, err := d.orm.Tx(ctx)
	if err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: begin tx: %w", err)
	}
	committed := false
	defer func() {
		if !committed {
			_ = tx.Rollback()
		}
	}()
	if _, err := tx.IdempotencyKey.Create().
		SetKey(cycleKey(scopeReverse, batchRef, cycle)).SetScope(scopeReverse).SetTenantID(p.TenantID).SetStatus("processed").
		Save(ctx); err != nil {
		if ent.IsConstraintError(err) {
			return DisburseResult{BatchRef: ref, AlreadyDone: true}, nil
		}
		return DisburseResult{}, fmt.Errorf("reverse: idem write: %w", err)
	}
	txPub := events.NewPublisher(tx.Client(), "erp")
	if err := txPub.Publish(ctx, p.TenantID, events.AggregateUUID(p.TenantID, ref), "payroll.reversed", payload); err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: publish: %w", err)
	}
	ids := make([]uuid.UUID, len(slips))
	for i, s := range slips {
		ids[i] = s.ID
	}
	if _, err := tx.Payslip.Update().
		Where(payslip.IDIn(ids...), payslip.Published(false)).
		SetApprovalStatus("rejected").
		ClearBatchRef().
		Save(ctx); err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: flip payslips: %w", err)
	}
	// Undo the batch's recoverable write-back and re-open any staff-purchase balances in POS.
	reversals, err := reverseRecoveries(ctx, tx, p.TenantID, ids, ref)
	if err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: undo recoveries: %w", err)
	}
	for _, st := range reversals {
		if err := txPub.Publish(ctx, p.TenantID, st.PurchaseID, "staff_purchase.recovery_reversed", map[string]any{
			"staff_purchase_id":      st.PurchaseID.String(),
			"source_key":             st.SourceKey,
			"origin":                 st.Origin,
			"pos_reference":          st.POSReference,
			"amount_recovered":       st.AmountRecovered.StringFixed(2), // negative delta
			"amount_recovered_total": st.AmountRecoveredTotal.StringFixed(2),
			"outstanding":            st.Outstanding.StringFixed(2),
			"settled":                false,
			"batch_ref":              ref,
			"period":                 p.Period.Format("2006-01-02"),
		}); err != nil {
			return DisburseResult{}, fmt.Errorf("reverse: publish staff_purchase.recovery_reversed: %w", err)
		}
	}
	if err := tx.Commit(); err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: commit: %w", err)
	}
	committed = true
	return DisburseResult{BatchRef: ref, Count: len(slips), NetTotal: netTotal}, nil
}

// selectPayslips returns the run's approved payslips that are not yet posted for payment.
func (d *Disburser) selectPayslips(ctx context.Context, p DisburseParams) ([]*ent.Payslip, error) {
	q := d.orm.Payslip.Query().Where(runScope(p.TenantID, p.Period, p.OutletID)...).
		Where(payslip.ApprovalStatus("approved"))
	if len(p.PayslipIDs) > 0 {
		q = q.Where(payslip.IDIn(p.PayslipIDs...))
	}
	return q.Order(ent.Asc(payslip.FieldID)).All(ctx)
}
