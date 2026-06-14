package payroll

import (
	"context"
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
	TenantID    uuid.UUID
	OutletID    uuid.UUID // uuid.Nil = all outlets
	Period      time.Time
	PayslipIDs  []uuid.UUID // optional explicit selection
	IdemKey     string      // client Idempotency-Key (optional; batch_ref used otherwise)
}

// DisburseResult summarises the outcome.
type DisburseResult struct {
	BatchRef       string          `json:"batch_ref"`
	Published      bool            `json:"published"`
	Disbursed      bool            `json:"disbursed"`
	Count          int             `json:"count"`
	NetTotal       decimal.Decimal `json:"net_total"`
	DisburseError  string          `json:"disburse_error,omitempty"`
	AlreadyDone    bool            `json:"already_done,omitempty"`
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
	payload, netTotal := buildPayrollEvent(slips, empByID, p, batchRef)

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
	if err := txPub.Publish(ctx, p.TenantID, batchRef, "payroll.processed", payload); err != nil {
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
	if err := tx.Commit(); err != nil {
		return DisburseResult{}, fmt.Errorf("disburse: commit: %w", err)
	}
	committed = true

	res := DisburseResult{BatchRef: batchRef, Published: true, Count: len(slips), NetTotal: netTotal}

	// Best-effort S2S disburse (transport failure does NOT roll back the GL event).
	payouts := buildPayouts(payload, batchRef, p.Period)
	if d.treasury != nil {
		if err := d.treasury.Disburse(ctx, p.TenantID, payouts, idemKey); err != nil {
			res.DisburseError = err.Error()
			d.log.Warn("treasury disburse failed (GL event already published)", zap.String("batch", batchRef), zap.Error(err))
		} else {
			res.Disbursed = true
		}
	}
	return res, nil
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
