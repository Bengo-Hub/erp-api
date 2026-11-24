package payroll

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/outboxevent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

// fakeTreasury records every batch it receives. pending makes it answer like a batch waiting
// for finance approval; fail lists references it reports as not dispatched.
type fakeTreasury struct {
	pending bool
	fail    map[string]bool
	keys    []string
	batches [][]treasury.Payout
}

func (f *fakeTreasury) DisburseBatch(_ context.Context, _ uuid.UUID, payouts []treasury.Payout, key string) (treasury.BatchResult, error) {
	f.keys = append(f.keys, key)
	f.batches = append(f.batches, payouts)
	if f.pending {
		return treasury.BatchResult{}, treasury.ErrApprovalPending
	}
	res := treasury.BatchResult{Count: len(payouts)}
	for _, p := range payouts {
		st := "dispatched"
		if f.fail[p.ReferenceID] {
			st = "failed"
		} else {
			res.Dispatched++
		}
		res.Results = append(res.Results, treasury.ItemOutcome{Reference: p.ReferenceID, Status: st})
	}
	return res, nil
}

type disburseFixture struct {
	client  *ent.Client
	svc     *Service
	engine  *approvals.Service
	d       *Disburser
	tr      *fakeTreasury
	tenant  uuid.UUID
	period  time.Time
	slips   []*ent.Payslip
	params  DisburseParams
	context context.Context
}

func newDisburseFixture(t *testing.T) *disburseFixture {
	t.Helper()
	client := testClient(t)
	ctx := context.Background()
	f := &disburseFixture{client: client, context: ctx, tenant: uuid.New(),
		period: time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC), tr: &fakeTreasury{fail: map[string]bool{}}}
	for _, name := range []string{"Asha", "Baraka"} {
		e := client.Employee.Create().SetTenantID(f.tenant).SetFirstName(name).SaveX(ctx)
		f.slips = append(f.slips, client.Payslip.Create().SetTenantID(f.tenant).SetEmployeeID(e.ID).
			SetPaymentPeriod(f.period).SetPayrollStatus("complete").
			SetGrossPay(decimal.NewFromInt(50000)).SetNetPay(decimal.NewFromInt(40000)).SaveX(ctx))
	}
	f.svc = NewService(client, nil)
	f.engine = approvals.NewService(client, nil)
	f.svc.SetApprovals(f.engine)
	f.d = NewDisburser(client, nil, nil, zap.NewNop())
	f.d.treasury = f.tr
	f.params = DisburseParams{TenantID: f.tenant, Period: f.period}
	return f
}

func (f *disburseFixture) approveRun(t *testing.T) {
	t.Helper()
	ra, err := f.svc.SubmitRunForApproval(f.context, f.tenant, f.period, uuid.Nil, nil)
	if err != nil || ra.Status != "pending" || ra.RequestID == nil {
		t.Fatalf("submit = %+v, %v", ra, err)
	}
	dec, err := f.engine.DecideAndApply(f.context, f.tenant, approvals.DecisionInput{RequestID: *ra.RequestID, Approve: true})
	if err != nil || dec.ApplyErr != nil {
		t.Fatalf("decide = %v / %v", err, dec.ApplyErr)
	}
}

func (f *disburseFixture) events(t *testing.T, eventType string) int {
	t.Helper()
	return f.client.OutboxEvent.Query().Where(outboxevent.TenantID(f.tenant), outboxevent.EventType(eventType)).CountX(f.context)
}

func (f *disburseFixture) paid(t *testing.T) int {
	t.Helper()
	return f.client.Payslip.Query().Where(payslip.TenantID(f.tenant), payslip.Published(true)).CountX(f.context)
}

// An unapproved run is neither posted nor paid; the approvals engine (with the fallback step for
// a tenant without a payroll workflow) is the only way to approve it.
func TestIntegration_DisburseRequiresApproval(t *testing.T) {
	f := newDisburseFixture(t)
	if _, err := f.d.Disburse(f.context, f.params); !errors.Is(err, ErrRunNotApproved) {
		t.Fatalf("disburse before approval: err = %v, want ErrRunNotApproved", err)
	}
	if n := f.events(t, "payroll.processed"); n != 0 || len(f.tr.keys) != 0 {
		t.Fatalf("unapproved run posted %d events and %d payout calls", n, len(f.tr.keys))
	}
	// Submitting puts the run up for approval; it is still not payable while pending.
	ra, err := f.svc.SubmitRunForApproval(f.context, f.tenant, f.period, uuid.Nil, nil)
	if err != nil || ra.Status != "pending" {
		t.Fatalf("submit = %+v, %v", ra, err)
	}
	again, _ := f.svc.SubmitRunForApproval(f.context, f.tenant, f.period, uuid.Nil, nil)
	if again.RequestID == nil || *again.RequestID != *ra.RequestID {
		t.Fatalf("a second submit opened another request")
	}
	if _, err := f.d.Disburse(f.context, f.params); !errors.Is(err, ErrRunNotApproved) {
		t.Fatalf("disburse while pending: err = %v", err)
	}
	if _, err := f.engine.DecideAndApply(f.context, f.tenant, approvals.DecisionInput{RequestID: *ra.RequestID, Approve: true}); err != nil {
		t.Fatal(err)
	}
	st, _ := f.svc.GetRunStatus(f.context, f.tenant, f.period, uuid.Nil)
	if st.Approved != 2 || !st.CanDisburse || st.CanReverse {
		t.Fatalf("status after approval = %+v", st)
	}
	res, err := f.d.Disburse(f.context, f.params)
	if err != nil || !res.Published || !res.Disbursed || res.Paid != 2 {
		t.Fatalf("disburse after approval = %+v, %v", res, err)
	}
}

// Treasury holding the batch for finance approval leaves it posted but unpaid; a retry re-sends
// the same batch under the same key, and only a dispatch marks payslips paid.
func TestIntegration_DisburseRetryAfterTreasuryApproval(t *testing.T) {
	f := newDisburseFixture(t)
	f.approveRun(t)

	f.tr.pending = true
	res, err := f.d.Disburse(f.context, f.params)
	if err != nil || !res.Published || !res.PendingApproval || res.Disbursed {
		t.Fatalf("first disburse = %+v, %v", res, err)
	}
	if f.paid(t) != 0 {
		t.Fatal("payslips marked paid while treasury approval is pending")
	}

	f.tr.pending = false
	f.tr.fail[f.tr.batches[0][1].ReferenceID] = true
	res, err = f.d.Disburse(f.context, f.params)
	if err != nil || res.Disbursed || res.Paid != 1 || res.DisburseError == "" {
		t.Fatalf("partial disburse = %+v, %v", res, err)
	}

	delete(f.tr.fail, f.tr.batches[0][1].ReferenceID)
	res, err = f.d.Disburse(f.context, f.params)
	if err != nil || !res.Disbursed || res.Paid != 2 {
		t.Fatalf("final disburse = %+v, %v", res, err)
	}
	if len(f.tr.keys) != 3 || f.tr.keys[0] != f.tr.keys[2] {
		t.Fatalf("treasury keys = %v, want three calls with one key", f.tr.keys)
	}
	for i := range f.tr.batches[0] {
		if f.tr.batches[0][i] != f.tr.batches[2][i] {
			t.Fatalf("retry sent a different batch: %+v vs %+v", f.tr.batches[0][i], f.tr.batches[2][i])
		}
	}
	// Done: no further treasury call, and the GL event was written once.
	res, err = f.d.Disburse(f.context, f.params)
	if err != nil || !res.AlreadyDone || len(f.tr.keys) != 3 {
		t.Fatalf("disburse after done = %+v, %v (calls %d)", res, err, len(f.tr.keys))
	}
	if n := f.events(t, "payroll.processed"); n != 1 {
		t.Fatalf("payroll.processed events = %d, want 1", n)
	}
	// A paid batch cannot be reversed.
	if _, err := f.d.Reverse(f.context, f.params); !errors.Is(err, ErrBatchPaid) {
		t.Fatalf("reverse after payment: err = %v, want ErrBatchPaid", err)
	}
}

// A posted, unpaid batch can be reversed once; the payslips go back for approval and a new
// posting cycle uses a new batch ref so treasury books it again.
func TestIntegration_ReverseUnpaidBatch(t *testing.T) {
	f := newDisburseFixture(t)
	f.approveRun(t)
	f.tr.pending = true
	first, err := f.d.Disburse(f.context, f.params)
	if err != nil || !first.Published {
		t.Fatalf("disburse = %+v, %v", first, err)
	}
	st, _ := f.svc.GetRunStatus(f.context, f.tenant, f.period, uuid.Nil)
	if !st.CanReverse || st.Posted != 2 {
		t.Fatalf("status before reverse = %+v", st)
	}
	if _, err := f.svc.RejectRun(f.context, f.tenant, f.period, uuid.Nil); !errors.Is(err, ErrRunPosted) {
		t.Fatalf("reject a posted run: err = %v", err)
	}
	if _, err := f.d.Reverse(f.context, f.params); err != nil {
		t.Fatal(err)
	}
	if _, err := f.d.Reverse(f.context, f.params); !errors.Is(err, ErrNothingToReverse) {
		t.Fatalf("second reverse: err = %v", err)
	}
	if n := f.events(t, "payroll.reversed"); n != 1 {
		t.Fatalf("payroll.reversed events = %d, want 1", n)
	}
	if _, err := f.d.Disburse(f.context, f.params); !errors.Is(err, ErrRunNotApproved) {
		t.Fatalf("disburse after reverse: err = %v, want ErrRunNotApproved", err)
	}
	f.approveRun(t)
	f.tr.pending = false
	second, err := f.d.Disburse(f.context, f.params)
	if err != nil || !second.Disbursed {
		t.Fatalf("disburse after re-approval = %+v, %v", second, err)
	}
	if second.BatchRef == first.BatchRef {
		t.Fatalf("new cycle reused batch ref %s", second.BatchRef)
	}
	// Payout references do not change between cycles, so treasury never pays an employee twice.
	last := f.tr.batches[len(f.tr.batches)-1]
	if last[0].ReferenceID != f.tr.batches[0][0].ReferenceID {
		t.Fatalf("payout reference changed across cycles: %s vs %s", last[0].ReferenceID, f.tr.batches[0][0].ReferenceID)
	}
}

// Taxable approved claims are paid once, through the payslip of the period that carries them,
// and are marked paid when that payslip's net pay is dispatched.
func TestIntegration_TaxableClaimsPaidThroughPayroll(t *testing.T) {
	f := newDisburseFixture(t)
	ctx := f.context
	emp := f.slips[0].EmployeeID
	taxable := f.client.ExpenseClaim.Create().SetTenantID(f.tenant).SetEmployeeID(emp).SetApproved(true).
		SetTaxable(true).SetAmount(decimal.NewFromInt(3000)).SaveX(ctx)
	f.client.ExpenseClaim.Create().SetTenantID(f.tenant).SetEmployeeID(emp).SetApproved(true).
		SetTaxable(false).SetAmount(decimal.NewFromInt(900)).SaveX(ctx)
	f.client.ExpenseClaim.Create().SetTenantID(f.tenant).SetEmployeeID(emp).SetApproved(false).
		SetTaxable(true).SetAmount(decimal.NewFromInt(700)).SaveX(ctx)

	emps := f.client.Employee.Query().AllX(ctx)
	got, err := f.svc.loadPayrollClaims(ctx, f.tenant, f.period, emps)
	if err != nil || len(got[emp]) != 1 || got[emp][0].ID != taxable.ID {
		t.Fatalf("claims for the run = %v, %v; want only the approved taxable claim", got[emp], err)
	}
	if err := f.svc.linkClaimsToPayslip(ctx, f.tenant, f.slips[0].ID, f.period, []uuid.UUID{taxable.ID}); err != nil {
		t.Fatal(err)
	}
	// The next period does not pick up a claim already carried by this period's payslip.
	next, _ := f.svc.loadPayrollClaims(ctx, f.tenant, f.period.AddDate(0, 1, 0), emps)
	if len(next[emp]) != 0 {
		t.Fatalf("claim carried into a second period")
	}
	f.approveRun(t)
	if _, err := f.d.Disburse(ctx, f.params); err != nil {
		t.Fatal(err)
	}
	if c := f.client.ExpenseClaim.GetX(ctx, taxable.ID); !c.IsPaid || c.PaymentDate == nil {
		t.Fatalf("taxable claim not marked paid after payout: %+v", c)
	}
}
