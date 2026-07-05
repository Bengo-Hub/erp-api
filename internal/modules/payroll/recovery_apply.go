package payroll

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/recoveryline"
)

// StaffPurchaseSettlement is emitted (per staff purchase) when a payroll batch recovers against a
// POS staff purchase, so the disburser can publish erp.staff_purchase.recovered and POS can pay
// down the linked layaway/credit balance.
type StaffPurchaseSettlement struct {
	PurchaseID           uuid.UUID
	SourceKey            string
	Origin               string
	POSReference         string
	AmountRecovered      decimal.Decimal // this period's delta
	AmountRecoveredTotal decimal.Decimal // cumulative
	Outstanding          decimal.Decimal
	Settled              bool
}

// ApplyRecoveries writes back the frozen RecoveryLine amounts for a disbursed batch to each
// recoverable (loan/advance/loss-damage/staff-purchase), exactly once, using the caller's tx so it
// commits atomically with the payroll.processed event + batch tagging. It returns the staff-purchase
// settlements for the caller to publish. Reversing a batch calls ReverseRecoveries.
//
// Double-count safety: only lines with applied=false are processed, and each is flipped applied=true
// + tagged with batch_ref in the same tx. The disburse idempotency key guards a re-sent request.
func applyRecoveries(ctx context.Context, tx *ent.Tx, tenantID uuid.UUID, payslipIDs []uuid.UUID, batchRef string) ([]StaffPurchaseSettlement, error) {
	if len(payslipIDs) == 0 {
		return nil, nil
	}
	lines, err := tx.RecoveryLine.Query().
		Where(
			recoveryline.TenantID(tenantID),
			recoveryline.PayslipIDIn(payslipIDs...),
			recoveryline.Applied(false),
		).All(ctx)
	if err != nil {
		return nil, err
	}
	var settlements []StaffPurchaseSettlement
	for _, ln := range lines {
		switch ln.RecoverableType {
		case recoveryline.RecoverableTypeLoan:
			l, e := tx.EmployeeLoan.Get(ctx, ln.RecoverableID)
			if e != nil {
				return nil, e
			}
			repaid := l.AmountRepaid.Add(ln.Amount)
			upd := tx.EmployeeLoan.UpdateOneID(l.ID).
				SetAmountRepaid(repaid).
				SetNoOfInstallmentsPaid(l.NoOfInstallmentsPaid + 1)
			if repaid.GreaterThanOrEqual(l.PrincipalAmount) {
				upd = upd.SetIsActive(false)
			}
			if _, e := upd.Save(ctx); e != nil {
				return nil, e
			}
		case recoveryline.RecoverableTypeAdvance:
			a, e := tx.Advance.Get(ctx, ln.RecoverableID)
			if e != nil {
				return nil, e
			}
			repaid := a.AmountRepaid.Add(ln.Amount)
			upd := tx.Advance.UpdateOneID(a.ID).SetAmountRepaid(repaid)
			if repaid.GreaterThanOrEqual(a.AmountIssued) {
				upd = upd.SetIsActive(false)
			}
			if _, e := upd.Save(ctx); e != nil {
				return nil, e
			}
		case recoveryline.RecoverableTypeLossDamage:
			ld, e := tx.LossAndDamage.Get(ctx, ln.RecoverableID)
			if e != nil {
				return nil, e
			}
			repaid := ld.AmountRepaid.Add(ln.Amount)
			upd := tx.LossAndDamage.UpdateOneID(ld.ID).SetAmountRepaid(repaid)
			if repaid.GreaterThanOrEqual(ld.DamageAmount) {
				upd = upd.SetIsActive(false)
			}
			if _, e := upd.Save(ctx); e != nil {
				return nil, e
			}
		case recoveryline.RecoverableTypeStaffPurchase:
			sp, e := tx.StaffPurchaseDeduction.Get(ctx, ln.RecoverableID)
			if e != nil {
				return nil, e
			}
			recovered := sp.AmountRecovered.Add(ln.Amount)
			outstanding := sp.Principal.Sub(recovered)
			settled := outstanding.LessThanOrEqual(decimal.Zero)
			upd := tx.StaffPurchaseDeduction.UpdateOneID(sp.ID).
				SetAmountRecovered(recovered).
				SetLastSettledBatch(batchRef)
			if settled {
				upd = upd.SetStatus("settled").SetIsActive(false)
			}
			if _, e := upd.Save(ctx); e != nil {
				return nil, e
			}
			out := outstanding
			if out.IsNegative() {
				out = decimal.Zero
			}
			settlements = append(settlements, StaffPurchaseSettlement{
				PurchaseID:           sp.ID,
				SourceKey:            sp.SourceKey,
				Origin:               sp.Origin.String(),
				POSReference:         sp.PosReference,
				AmountRecovered:      ln.Amount,
				AmountRecoveredTotal: recovered,
				Outstanding:          out,
				Settled:              settled,
			})
		}
		if _, e := tx.RecoveryLine.UpdateOneID(ln.ID).SetApplied(true).SetBatchRef(batchRef).Save(ctx); e != nil {
			return nil, e
		}
	}
	return settlements, nil
}

// ReverseRecoveries undoes a batch's write-back: it decrements each recoverable, re-activates it, and
// flips its RecoveryLines back to unapplied. Returns the staff-purchase reversals for the caller to
// publish erp.staff_purchase.recovery_reversed.
func reverseRecoveries(ctx context.Context, tx *ent.Tx, tenantID uuid.UUID, payslipIDs []uuid.UUID, batchRef string) ([]StaffPurchaseSettlement, error) {
	if len(payslipIDs) == 0 {
		return nil, nil
	}
	lines, err := tx.RecoveryLine.Query().
		Where(
			recoveryline.TenantID(tenantID),
			recoveryline.PayslipIDIn(payslipIDs...),
			recoveryline.Applied(true),
			recoveryline.BatchRef(batchRef),
		).All(ctx)
	if err != nil {
		return nil, err
	}
	var reversals []StaffPurchaseSettlement
	for _, ln := range lines {
		switch ln.RecoverableType {
		case recoveryline.RecoverableTypeLoan:
			l, e := tx.EmployeeLoan.Get(ctx, ln.RecoverableID)
			if e != nil {
				return nil, e
			}
			repaid := l.AmountRepaid.Sub(ln.Amount)
			pcount := l.NoOfInstallmentsPaid - 1
			if pcount < 0 {
				pcount = 0
			}
			if _, e := tx.EmployeeLoan.UpdateOneID(l.ID).SetAmountRepaid(clampZero(repaid)).SetNoOfInstallmentsPaid(pcount).SetIsActive(true).Save(ctx); e != nil {
				return nil, e
			}
		case recoveryline.RecoverableTypeAdvance:
			a, e := tx.Advance.Get(ctx, ln.RecoverableID)
			if e != nil {
				return nil, e
			}
			if _, e := tx.Advance.UpdateOneID(a.ID).SetAmountRepaid(clampZero(a.AmountRepaid.Sub(ln.Amount))).SetIsActive(true).Save(ctx); e != nil {
				return nil, e
			}
		case recoveryline.RecoverableTypeLossDamage:
			ld, e := tx.LossAndDamage.Get(ctx, ln.RecoverableID)
			if e != nil {
				return nil, e
			}
			if _, e := tx.LossAndDamage.UpdateOneID(ld.ID).SetAmountRepaid(clampZero(ld.AmountRepaid.Sub(ln.Amount))).SetIsActive(true).Save(ctx); e != nil {
				return nil, e
			}
		case recoveryline.RecoverableTypeStaffPurchase:
			sp, e := tx.StaffPurchaseDeduction.Get(ctx, ln.RecoverableID)
			if e != nil {
				return nil, e
			}
			recovered := clampZero(sp.AmountRecovered.Sub(ln.Amount))
			if _, e := tx.StaffPurchaseDeduction.UpdateOneID(sp.ID).SetAmountRecovered(recovered).SetStatus("active").SetIsActive(true).Save(ctx); e != nil {
				return nil, e
			}
			reversals = append(reversals, StaffPurchaseSettlement{
				PurchaseID:           sp.ID,
				SourceKey:            sp.SourceKey,
				Origin:               sp.Origin.String(),
				POSReference:         sp.PosReference,
				AmountRecovered:      ln.Amount.Neg(),
				AmountRecoveredTotal: recovered,
				Outstanding:          sp.Principal.Sub(recovered),
				Settled:              false,
			})
		}
		if _, e := tx.RecoveryLine.UpdateOneID(ln.ID).SetApplied(false).SetBatchRef("").Save(ctx); e != nil {
			return nil, e
		}
	}
	return reversals, nil
}

func clampZero(d decimal.Decimal) decimal.Decimal {
	if d.IsNegative() {
		return decimal.Zero
	}
	return d
}
