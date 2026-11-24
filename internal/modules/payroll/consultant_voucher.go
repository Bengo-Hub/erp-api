package payroll

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/consultantvoucher"
)

// WHTRatesKey is the app setting that holds the tenant's withholding tax rates on consultancy
// fees. Resident and non-resident payees always have separate rates.
const WHTRatesKey = "payroll.wht_rates"

// WHTRates are the tenant's withholding tax rates on consultancy fees, in percent.
type WHTRates struct {
	Resident    decimal.Decimal `json:"resident_rate"`
	NonResident decimal.Decimal `json:"non_resident_rate"`
}

// DefaultWHTRates are the KRA rates on professional and consultancy fees.
func DefaultWHTRates() WHTRates {
	return WHTRates{Resident: decimal.NewFromInt(5), NonResident: decimal.NewFromInt(20)}
}

// Validate checks both rates are percentages between 0 and 100.
func (r WHTRates) Validate() error {
	for name, v := range map[string]decimal.Decimal{"resident_rate": r.Resident, "non_resident_rate": r.NonResident} {
		if v.IsNegative() || v.GreaterThan(decimal.NewFromInt(100)) {
			return fmt.Errorf("%s must be between 0 and 100", name)
		}
	}
	return nil
}

// fraction is the rate that applies to a payee, as a fraction of the gross.
func (r WHTRates) fraction(resident bool) decimal.Decimal {
	if resident {
		return r.Resident.Div(decimal.NewFromInt(100))
	}
	return r.NonResident.Div(decimal.NewFromInt(100))
}

// GetWHTRates returns the tenant's WHT rates, or the defaults when none are saved.
func (s *Service) GetWHTRates(ctx context.Context, tenantID uuid.UUID) (WHTRates, error) {
	row, err := s.orm.AppSetting.Query().
		Where(appsetting.TenantID(tenantID), appsetting.AppKey(WHTRatesKey)).Only(ctx)
	if ent.IsNotFound(err) {
		return DefaultWHTRates(), nil
	}
	if err != nil {
		return WHTRates{}, fmt.Errorf("payroll: load wht rates: %w", err)
	}
	r := DefaultWHTRates()
	if err := json.Unmarshal([]byte(row.Value), &r); err != nil {
		return WHTRates{}, fmt.Errorf("payroll: decode wht rates: %w", err)
	}
	return r, nil
}

// SaveWHTRates validates and stores the tenant's WHT rates.
func (s *Service) SaveWHTRates(ctx context.Context, tenantID uuid.UUID, r WHTRates) (WHTRates, error) {
	if err := r.Validate(); err != nil {
		return WHTRates{}, err
	}
	raw, err := json.Marshal(r)
	if err != nil {
		return WHTRates{}, err
	}
	if err := s.orm.AppSetting.Create().
		SetTenantID(tenantID).SetAppKey(WHTRatesKey).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).
		UpdateNewValues().Exec(ctx); err != nil {
		return WHTRates{}, fmt.Errorf("payroll: save wht rates: %w", err)
	}
	return r, nil
}

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

// resolveWHTRate returns the WHT rate (as a fraction) for a resident or non-resident payee from
// the tenant's rates.
func (s *Service) resolveWHTRate(ctx context.Context, tenantID uuid.UUID, resident bool) (decimal.Decimal, error) {
	rates, err := s.GetWHTRates(ctx, tenantID)
	if err != nil {
		return decimal.Zero, err
	}
	return rates.fraction(resident), nil
}

// CreateConsultantVoucher computes WHT + net and persists a draft voucher.
func (s *Service) CreateConsultantVoucher(ctx context.Context, tenantID uuid.UUID, in ConsultantVoucherInput) (*ent.ConsultantVoucher, error) {
	if in.EmployeeID == uuid.Nil {
		return nil, fmt.Errorf("a consultant is required")
	}
	if in.GrossAmount.LessThanOrEqual(decimal.Zero) {
		return nil, fmt.Errorf("gross amount must be greater than zero")
	}
	rate, err := s.resolveWHTRate(ctx, tenantID, in.IsResident)
	if err != nil {
		return nil, err
	}
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
		currency := updated.Currency
		if currency == "" {
			currency = "KES"
		}
		projectID := ""
		if updated.ProjectID != nil {
			projectID = updated.ProjectID.String()
		}
		costCenter := ""
		if updated.CostCenterID != nil {
			costCenter = updated.CostCenterID.String()
		}
		// CRITICAL INVARIANT: treasury skips the entry unless the emitted strings satisfy
		// amount_net + wht_amount + deductions == amount_gross. Round gross/wht/deductions to 2dp
		// then DERIVE net from those rounded values so the four emitted strings always reconcile
		// (avoids a 1-cent residual from rounding each stored decimal independently).
		gross2 := updated.GrossAmount.Round(2)
		wht2 := updated.WhtAmount.Round(2)
		ded2 := updated.DeductionsAmount.Round(2)
		net2 := gross2.Sub(wht2).Sub(ded2)
		payload := map[string]any{
			"voucher_id":    updated.ID.String(),
			"tenant_id":     tenantID.String(),
			"consultant_id": updated.EmployeeID.String(),
			"amount_gross":  gross2.StringFixed(2),
			"wht_rate":      updated.WhtRate.String(),
			"wht_amount":    wht2.StringFixed(2),
			"deductions":    ded2.StringFixed(2),
			"amount_net":    net2.StringFixed(2),
			"currency":      currency,
			"period":        period,
			"reference_id":  updated.ID.String(),
			"project_id":    projectID,
			"cost_center":   costCenter,
		}
		if err := s.publisher.Publish(ctx, tenantID, updated.ID, "consultant_voucher.approved", payload); err != nil {
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
