package payroll

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/consultantvoucher"
	"github.com/Bengo-Hub/erp-api/internal/ent/withholdingtax"
)

// Default WHT rates on professional/consultancy fees (KRA): resident 5%, non-resident 20%.
var (
	whtResident    = decimal.RequireFromString("0.05")
	whtNonResident = decimal.RequireFromString("0.20")
)

// ConsultantVoucherInput is the create payload for a consultant payment voucher.
type ConsultantVoucherInput struct {
	EmployeeID       uuid.UUID
	DocNumber        string
	Title            string
	Period           *time.Time
	GrossAmount      decimal.Decimal
	DeductionsAmount decimal.Decimal
	IsResident       bool
	ProjectID        *uuid.UUID
	CostCenterID     *uuid.UUID
	CreatedBy        *uuid.UUID
}

// resolveWHTRate returns the configured active WHT rate for the tenant (as a fraction), falling
// back to the statutory resident/non-resident professional-fee rate. A configured rate > 1 is
// treated as a percentage (e.g. 5 → 0.05).
func (s *Service) resolveWHTRate(ctx context.Context, tenantID uuid.UUID, resident bool) decimal.Decimal {
	rows, err := s.orm.WithHoldingTax.Query().
		Where(withholdingtax.TenantID(tenantID), withholdingtax.IsActive(true)).
		Order(ent.Desc(withholdingtax.FieldCreatedAt)).Limit(1).All(ctx)
	if err == nil && len(rows) == 1 {
		r := rows[0].Rate
		if r.GreaterThan(decimal.NewFromInt(1)) {
			r = r.Div(decimal.NewFromInt(100))
		}
		if r.GreaterThan(decimal.Zero) {
			return r
		}
	}
	if resident {
		return whtResident
	}
	return whtNonResident
}

// CreateConsultantVoucher computes WHT + net and persists a draft voucher.
func (s *Service) CreateConsultantVoucher(ctx context.Context, tenantID uuid.UUID, in ConsultantVoucherInput) (*ent.ConsultantVoucher, error) {
	if in.EmployeeID == uuid.Nil {
		return nil, fmt.Errorf("a consultant is required")
	}
	if in.GrossAmount.LessThanOrEqual(decimal.Zero) {
		return nil, fmt.Errorf("gross amount must be greater than zero")
	}
	rate := s.resolveWHTRate(ctx, tenantID, in.IsResident)
	wht := in.GrossAmount.Mul(rate).Round(2)
	net := in.GrossAmount.Sub(wht).Sub(in.DeductionsAmount).Round(2)

	c := s.orm.ConsultantVoucher.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetGrossAmount(in.GrossAmount).
		SetDeductionsAmount(in.DeductionsAmount).
		SetWhtRate(rate).
		SetWhtAmount(wht).
		SetNetAmount(net).
		SetIsResident(in.IsResident).
		SetNillableProjectID(in.ProjectID).
		SetNillableCostCenterID(in.CostCenterID).
		SetNillableCreatedBy(in.CreatedBy).
		SetNillablePeriod(in.Period)
	if in.DocNumber != "" {
		c = c.SetDocNumber(in.DocNumber)
	}
	if in.Title != "" {
		c = c.SetTitle(in.Title)
	}
	return c.Save(ctx)
}

// ListConsultantVouchers returns the tenant's vouchers (newest first), optionally filtered by status.
func (s *Service) ListConsultantVouchers(ctx context.Context, tenantID uuid.UUID, status string, limit, offset int) ([]*ent.ConsultantVoucher, int, decimal.Decimal, error) {
	q := s.orm.ConsultantVoucher.Query().Where(consultantvoucher.TenantID(tenantID), consultantvoucher.DeleteStatus(false))
	if status != "" {
		q = q.Where(consultantvoucher.StatusEQ(consultantvoucher.Status(status)))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, decimal.Zero, err
	}
	rows, err := q.Order(ent.Desc(consultantvoucher.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, decimal.Zero, err
	}
	pageTotal := decimal.Zero
	for _, r := range rows {
		pageTotal = pageTotal.Add(r.NetAmount)
	}
	return rows, total, pageTotal, nil
}

// GetConsultantVoucher fetches one voucher.
func (s *Service) GetConsultantVoucher(ctx context.Context, tenantID, id uuid.UUID) (*ent.ConsultantVoucher, error) {
	return s.orm.ConsultantVoucher.Query().
		Where(consultantvoucher.ID(id), consultantvoucher.TenantID(tenantID), consultantvoucher.DeleteStatus(false)).Only(ctx)
}

// DeleteConsultantVoucher soft-deletes a voucher.
func (s *Service) DeleteConsultantVoucher(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.ConsultantVoucher.Update().
		Where(consultantvoucher.ID(id), consultantvoucher.TenantID(tenantID)).
		SetDeleteStatus(true).Save(ctx)
	if err != nil {
		return fmt.Errorf("consultant voucher: delete: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("consultant voucher: not found")
	}
	return nil
}

// ApproveConsultantVoucher approves a voucher and emits erp.consultant_voucher.approved so treasury
// posts the GL (DR 5600 consultant fees / CR 2050 AP net / CR 2550 WHT payable), attributed to the
// project/cost-center. Idempotent. The caller (handler) then pays the net via the treasury payout S2S.
func (s *Service) ApproveConsultantVoucher(ctx context.Context, tenantID, id, approverID uuid.UUID) (*ent.ConsultantVoucher, error) {
	existing, err := s.GetConsultantVoucher(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if existing.Status == consultantvoucher.StatusApproved || existing.Status == consultantvoucher.StatusPaid {
		return existing, nil // idempotent
	}
	updated, err := existing.Update().
		SetStatus(consultantvoucher.StatusApproved).
		SetNillableApproverID(&approverID).
		SetApprovedAt(time.Now()).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("consultant voucher: approve: %w", err)
	}
	if s.publisher != nil {
		period := ""
		if updated.Period != nil {
			period = updated.Period.Format("2006-01")
		}
		payload := map[string]any{
			"voucher_id":   updated.ID.String(),
			"tenant_id":    tenantID.String(),
			"consultant_id": updated.EmployeeID.String(),
			"amount_gross": updated.GrossAmount.StringFixed(2),
			"wht_rate":     updated.WhtRate.String(),
			"wht_amount":   updated.WhtAmount.StringFixed(2),
			"deductions":   updated.DeductionsAmount.StringFixed(2),
			"amount_net":   updated.NetAmount.StringFixed(2),
			"currency":     updated.Currency,
			"period":       period,
			"reference_id": updated.ID.String(),
		}
		if updated.ProjectID != nil {
			payload["project_id"] = updated.ProjectID.String()
		}
		if updated.CostCenterID != nil {
			payload["cost_center"] = updated.CostCenterID.String()
		}
		if err := s.publisher.Publish(ctx, tenantID, updated.ID.String(), "consultant_voucher.approved", payload); err != nil {
			return updated, fmt.Errorf("consultant voucher: publish approved: %w", err)
		}
	}
	return updated, nil
}

// MarkConsultantVoucherPaid flags the voucher published/paid after a successful net payout.
func (s *Service) MarkConsultantVoucherPaid(ctx context.Context, tenantID, id uuid.UUID) error {
	_, err := s.orm.ConsultantVoucher.Update().
		Where(consultantvoucher.ID(id), consultantvoucher.TenantID(tenantID)).
		SetStatus(consultantvoucher.StatusPaid).SetPublished(true).Save(ctx)
	return err
}

// SetConsultantVoucherEmailStatus records the email delivery status (e.g. "Sent").
func (s *Service) SetConsultantVoucherEmailStatus(ctx context.Context, tenantID, id uuid.UUID, status string) error {
	_, err := s.orm.ConsultantVoucher.Update().
		Where(consultantvoucher.ID(id), consultantvoucher.TenantID(tenantID)).
		SetEmailStatus(status).Save(ctx)
	return err
}
