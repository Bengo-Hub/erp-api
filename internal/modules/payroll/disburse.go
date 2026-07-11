package payroll

import (
	"context"
	"errors"
	"fmt"
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

// Disburser publishes erp.payroll.processed (GL) atomically with the payroll mutation and
// requests net-pay disbursement from treasury. Idempotent per batch (gaps §2.8).
type Disburser struct {
	orm       *ent.Client
	publisher *events.Publisher
	treasury  *treasury.Client
	log       *zap.Logger
}

func NewDisburser(orm *ent.Client, publisher *events.Publisher, treasuryClient *treasury.Client, log *zap.Logger) *Disburser {
	return &Disburser{orm: orm, publisher: publisher, treasury: treasuryClient, log: log.Named("payroll.disburse")}
}

// DisburseParams selects the batch to disburse.
type DisburseParams struct {
	TenantID   uuid.UUID
	OutletID   uuid.UUID // uuid.Nil = all outlets
	Period     time.Time
	PayslipIDs []uuid.UUID // optional explicit selection
	IdemKey    string      // client Idempotency-Key (optional; batch_ref used otherwise)
}

// DisburseResult summarises the outcome.
type DisburseResult struct {
	BatchRef        string          `json:"batch_ref"`
	Published       bool            `json:"published"`
	Disbursed       bool            `json:"disbursed"`
	Count           int             `json:"count"`
	NetTotal        decimal.Decimal `json:"net_total"`
	DisburseError   string          `json:"disburse_error,omitempty"`
	AlreadyDone     bool            `json:"already_done,omitempty"`
	PendingApproval bool            `json:"pending_approval,omitempty"` // treasury requires finance approval (+OTP) first
}

// Disburse selects approved+complete payslips, publishes the GL event in a tx, persists
// the batch_ref, then best-effort calls treasury. A per-batch idempotency guard prevents
// a duplicate GL event / payout request on a re-sent POST (gaps §2.8).
func (d *Disburser) Disburse(ctx context.Context, p DisburseParams) (DisburseResult, error) {
	batchRef := buildBatchRef(p.TenantID, p.Period, p.OutletID)
	idemKey := p.IdemKey
	if idemKey == "" {
		idemKey = batchRef
	}

	// Idempotency guard: if we already processed this batch, short-circuit.
	if exists, err := d.orm.IdempotencyKey.Query().
		Where(idempotencykey.Key(idemKey), idempotencykey.Scope("payroll.disburse")).
		Exist(ctx); err != nil {
		return DisburseResult{}, fmt.Errorf("disburse: idem check: %w", err)
	} else if exists {
		return DisburseResult{BatchRef: batchRef, AlreadyDone: true, Published: true}, nil
	}

	slips, err := d.selectPayslips(ctx, p)
	if err != nil {
		return DisburseResult{}, err
	}
	if len(slips) == 0 {
		return DisburseResult{BatchRef: batchRef, Published: false}, nil
	}

	empByID, err := d.loadEmployees(ctx, p.TenantID, slips)
	if err != nil {
		return DisburseResult{}, err
	}
	prefs := d.loadPayoutPrefs(ctx, p.TenantID, slips)
	payload, netTotal := buildPayrollEvent(slips, empByID, prefs, p, batchRef)

	// Atomic: write outbox event + batch_ref on payslips + idempotency key in one tx.
	tx, err := d.orm.Tx(ctx)
	if err != nil {
		return DisburseResult{}, fmt.Errorf("disburse: begin tx: %w", err)
	}
	committed := false
	defer func() {
		if !committed {
			_ = tx.Rollback()
		}
	}()

	txPub := events.NewPublisher(tx.Client(), "erp")
	// aggregate_id MUST be a UUID — the shared-events poller scans it into uuid.UUID and a
	// non-UUID value (e.g. the batch_ref string) jams the WHOLE poller. Derive a stable UUID
	// from the batch ref; batch_ref itself stays in the payload.
	aggID := uuid.NewSHA1(p.TenantID, []byte(batchRef)).String()
	if err := txPub.Publish(ctx, p.TenantID, aggID, "payroll.processed", payload); err != nil {
		return DisburseResult{}, fmt.Errorf("disburse: publish: %w", err)
	}
	ids := make([]uuid.UUID, len(slips))
	for i, s := range slips {
		ids[i] = s.ID
	}
	if _, err := tx.Payslip.Update().
		Where(payslip.IDIn(ids...)).
		SetBatchRef(batchRef).
		SetApprovalStatus("approved").
		Save(ctx); err != nil {
		return DisburseResult{}, fmt.Errorf("disburse: tag batch: %w", err)
	}
	if _, err := tx.IdempotencyKey.Create().
		SetKey(idemKey).
		SetScope("payroll.disburse").
		SetTenantID(p.TenantID).
		SetStatus("processed").
		Save(ctx); err != nil {
		return DisburseResult{}, fmt.Errorf("disburse: idem write: %w", err)
	}
	// Persist repayment write-back for every recoverable this batch recovered (loans/advances/
	// loss-damages/staff-purchases), atomically with the GL event + batch tag (gaps §2.7). For
	// staff purchases, publish erp.staff_purchase.recovered in the SAME tx so POS pays down the
	// linked layaway/credit balance.
	settlements, err := applyRecoveries(ctx, tx, p.TenantID, ids, batchRef)
	if err != nil {
		return DisburseResult{}, fmt.Errorf("disburse: apply recoveries: %w", err)
	}
	for _, st := range settlements {
		if err := txPub.Publish(ctx, p.TenantID, st.PurchaseID.String(), "staff_purchase.recovered", map[string]any{
			"staff_purchase_id":      st.PurchaseID.String(),
			"source_key":             st.SourceKey,
			"origin":                 st.Origin,
			"pos_reference":          st.POSReference,
			"amount_recovered":       st.AmountRecovered.StringFixed(2),
			"amount_recovered_total": st.AmountRecoveredTotal.StringFixed(2),
			"outstanding":            st.Outstanding.StringFixed(2),
			"settled":                st.Settled,
			"batch_ref":              batchRef,
			"period":                 p.Period.Format("2006-01-02"),
		}); err != nil {
			return DisburseResult{}, fmt.Errorf("disburse: publish staff_purchase.recovered: %w", err)
		}
	}
	if err := tx.Commit(); err != nil {
		return DisburseResult{}, fmt.Errorf("disburse: commit: %w", err)
	}
	committed = true

	res := DisburseResult{BatchRef: batchRef, Published: true, Count: len(slips), NetTotal: netTotal}

	// Best-effort S2S disburse (transport failure does NOT roll back the GL event).
	payouts := buildPayouts(payload, batchRef, p.Period)
	if d.treasury != nil {
		if err := d.treasury.Disburse(ctx, p.TenantID, payouts, idemKey); err != nil {
			if errors.Is(err, treasury.ErrApprovalPending) {
				// Not a failure: treasury created a finance payroll-approval request. The GL event is
				// already published; the operator re-triggers disburse after approval (with OTP).
				res.PendingApproval = true
				res.DisburseError = "pending finance approval"
				d.log.Info("payroll disbursement pending finance approval in treasury", zap.String("batch", batchRef))
			} else {
				res.DisburseError = err.Error()
				d.log.Warn("treasury disburse failed (GL event already published)", zap.String("batch", batchRef), zap.Error(err))
			}
		} else {
			res.Disbursed = true
			// Confirmation loop: mark the batch's payslips published on synchronous treasury
			// success. treasury's disburse is synchronous (we have the result here), so we do
			// NOT depend on an async treasury.payout.completed event to close the loop. Leave
			// payslips unpublished on disburse failure so a later run can retry the payout.
			if _, err := d.orm.Payslip.Update().
				Where(payslip.IDIn(ids...)).
				SetPublished(true).
				Save(ctx); err != nil {
				d.log.Warn("mark payslips published failed (payout succeeded)", zap.String("batch", batchRef), zap.Error(err))
			}
		}
	}
	return res, nil
}

// Reverse reverses a previously-disbursed payroll batch: it publishes erp.payroll.reversed (which
// treasury consumes to post the inverse GL journal) and flips the batch's payslips back to
// unpublished + approval_status="rejected" so they can be corrected and re-run. Idempotent per
// batch via a dedicated reversal idempotency scope.
func (d *Disburser) Reverse(ctx context.Context, p DisburseParams) (DisburseResult, error) {
	batchRef := buildBatchRef(p.TenantID, p.Period, p.OutletID)
	idemKey := p.IdemKey
	if idemKey == "" {
		idemKey = batchRef
	}
	if exists, err := d.orm.IdempotencyKey.Query().
		Where(idempotencykey.Key(idemKey), idempotencykey.Scope("payroll.reverse")).
		Exist(ctx); err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: idem check: %w", err)
	} else if exists {
		return DisburseResult{BatchRef: batchRef, AlreadyDone: true}, nil
	}

	// Select the batch's payslips (those tagged with this batch_ref).
	slips, err := d.orm.Payslip.Query().Where(
		payslip.TenantID(p.TenantID),
		payslip.BatchRef(batchRef),
		payslip.DeleteStatus(false),
	).All(ctx)
	if err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: select payslips: %w", err)
	}
	if len(slips) == 0 {
		return DisburseResult{BatchRef: batchRef}, nil
	}
	empByID, err := d.loadEmployees(ctx, p.TenantID, slips)
	if err != nil {
		return DisburseResult{}, err
	}
	prefs := d.loadPayoutPrefs(ctx, p.TenantID, slips)
	payload, netTotal := buildPayrollEvent(slips, empByID, prefs, p, batchRef)

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
	txPub := events.NewPublisher(tx.Client(), "erp")
	aggID := uuid.NewSHA1(p.TenantID, []byte(batchRef)).String() // UUID aggregate_id (poller requires it)
	if err := txPub.Publish(ctx, p.TenantID, aggID, "payroll.reversed", payload); err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: publish: %w", err)
	}
	ids := make([]uuid.UUID, len(slips))
	for i, s := range slips {
		ids[i] = s.ID
	}
	if _, err := tx.Payslip.Update().
		Where(payslip.IDIn(ids...)).
		SetPublished(false).
		SetApprovalStatus("rejected").
		Save(ctx); err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: flip payslips: %w", err)
	}
	if _, err := tx.IdempotencyKey.Create().
		SetKey(idemKey).SetScope("payroll.reverse").SetTenantID(p.TenantID).SetStatus("processed").
		Save(ctx); err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: idem write: %w", err)
	}
	// Undo the batch's recoverable write-back and re-open any staff-purchase balances in POS.
	reversals, err := reverseRecoveries(ctx, tx, p.TenantID, ids, batchRef)
	if err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: undo recoveries: %w", err)
	}
	for _, st := range reversals {
		if err := txPub.Publish(ctx, p.TenantID, st.PurchaseID.String(), "staff_purchase.recovery_reversed", map[string]any{
			"staff_purchase_id":      st.PurchaseID.String(),
			"source_key":             st.SourceKey,
			"origin":                 st.Origin,
			"pos_reference":          st.POSReference,
			"amount_recovered":       st.AmountRecovered.StringFixed(2), // negative delta
			"amount_recovered_total": st.AmountRecoveredTotal.StringFixed(2),
			"outstanding":            st.Outstanding.StringFixed(2),
			"settled":                false,
			"batch_ref":              batchRef,
			"period":                 p.Period.Format("2006-01-02"),
		}); err != nil {
			return DisburseResult{}, fmt.Errorf("reverse: publish staff_purchase.recovery_reversed: %w", err)
		}
	}
	if err := tx.Commit(); err != nil {
		return DisburseResult{}, fmt.Errorf("reverse: commit: %w", err)
	}
	committed = true
	return DisburseResult{BatchRef: batchRef, Count: len(slips), NetTotal: netTotal}, nil
}

func (d *Disburser) selectPayslips(ctx context.Context, p DisburseParams) ([]*ent.Payslip, error) {
	q := d.orm.Payslip.Query().Where(
		payslip.TenantID(p.TenantID),
		payslip.PaymentPeriod(p.Period),
		payslip.DeleteStatus(false),
		payslip.PayrollStatus("complete"),
		payslip.Published(false),
	)
	if p.OutletID != uuid.Nil {
		q = q.Where(payslip.OutletID(p.OutletID))
	}
	if len(p.PayslipIDs) > 0 {
		q = q.Where(payslip.IDIn(p.PayslipIDs...))
	}
	return q.All(ctx)
}
