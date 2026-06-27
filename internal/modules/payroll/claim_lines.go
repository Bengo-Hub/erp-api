package payroll

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/claimitem"
	"github.com/Bengo-Hub/erp-api/internal/ent/expenseclaim"
	"github.com/Bengo-Hub/erp-api/internal/ent/mileageroute"
)

// This file wires the (previously dormant) ClaimItem line table and the NEW MileageRoute table
// so the claims form reaches full Wingubox parity:
//   - other/reimbursement claims -> itemized ClaimItem lines (date/description/type/amount)
//   - mileage claims             -> MileageRoute legs (from/to/distance/rate, amount = distance*rate)
// All queries are tenant-isolated and verify the parent claim belongs to the tenant.

// ---- Claim items (itemized lines) ----

// ClaimItemInput is the create payload for one itemized claim line.
type ClaimItemInput struct {
	ExpenseType string
	Description string
	Quantity    decimal.Decimal
	UnitCost    decimal.Decimal
	Amount      decimal.Decimal
}

// amount resolves the line amount: explicit Amount when > 0, else quantity × unit_cost.
func (in ClaimItemInput) amount() decimal.Decimal {
	if in.Amount.GreaterThan(decimal.Zero) {
		return in.Amount
	}
	if in.Quantity.GreaterThan(decimal.Zero) && in.UnitCost.GreaterThan(decimal.Zero) {
		return in.Quantity.Mul(in.UnitCost)
	}
	return in.Amount
}

func (s *Service) claimBelongs(ctx context.Context, tenantID, claimID uuid.UUID) error {
	ok, err := s.orm.ExpenseClaim.Query().
		Where(expenseclaim.ID(claimID), expenseclaim.TenantID(tenantID), expenseclaim.DeleteStatus(false)).
		Exist(ctx)
	if err != nil {
		return fmt.Errorf("payroll: claim check: %w", err)
	}
	if !ok {
		return fmt.Errorf("payroll: claim not found for tenant")
	}
	return nil
}

// ListClaimItems returns the itemized lines for a claim.
func (s *Service) ListClaimItems(ctx context.Context, tenantID, claimID uuid.UUID) ([]*ent.ClaimItem, error) {
	if err := s.claimBelongs(ctx, tenantID, claimID); err != nil {
		return nil, err
	}
	return s.orm.ClaimItem.Query().
		Where(claimitem.TenantID(tenantID), claimitem.ExpenseClaimID(claimID)).
		Order(ent.Asc(claimitem.FieldCreatedAt)).All(ctx)
}

// CreateClaimItem appends one itemized line and re-totals the claim amount.
func (s *Service) CreateClaimItem(ctx context.Context, tenantID, claimID uuid.UUID, in ClaimItemInput) (*ent.ClaimItem, error) {
	if err := s.claimBelongs(ctx, tenantID, claimID); err != nil {
		return nil, err
	}
	b := s.orm.ClaimItem.Create().
		SetTenantID(tenantID).
		SetExpenseClaimID(claimID).
		SetAmount(in.amount())
	if in.ExpenseType != "" {
		b = b.SetExpenseType(in.ExpenseType)
	}
	if in.Description != "" {
		b = b.SetDescription(in.Description)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("payroll: create claim item: %w", err)
	}
	if err := s.recomputeClaimFromItems(ctx, tenantID, claimID); err != nil {
		return row, err
	}
	return row, nil
}

// DeleteClaimItem removes one itemized line and re-totals the claim amount.
func (s *Service) DeleteClaimItem(ctx context.Context, tenantID, claimID, itemID uuid.UUID) error {
	n, err := s.orm.ClaimItem.Delete().
		Where(claimitem.ID(itemID), claimitem.TenantID(tenantID), claimitem.ExpenseClaimID(claimID)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("payroll: delete claim item: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("payroll: claim item not found")
	}
	return s.recomputeClaimFromItems(ctx, tenantID, claimID)
}

// recomputeClaimFromItems sets the claim amount to the sum of its itemized lines.
func (s *Service) recomputeClaimFromItems(ctx context.Context, tenantID, claimID uuid.UUID) error {
	items, err := s.orm.ClaimItem.Query().
		Where(claimitem.TenantID(tenantID), claimitem.ExpenseClaimID(claimID)).All(ctx)
	if err != nil {
		return fmt.Errorf("payroll: sum claim items: %w", err)
	}
	total := decimal.Zero
	for _, it := range items {
		total = total.Add(it.Amount)
	}
	_, err = s.orm.ExpenseClaim.Update().
		Where(expenseclaim.ID(claimID), expenseclaim.TenantID(tenantID)).
		SetAmount(total).Save(ctx)
	if err != nil {
		return fmt.Errorf("payroll: retotal claim: %w", err)
	}
	return nil
}

// ---- Mileage routes ----

// MileageRouteInput is the create payload for one mileage leg.
type MileageRouteInput struct {
	RouteDate    *time.Time
	FromLocation string
	ToLocation   string
	Distance     decimal.Decimal
	Rate         decimal.Decimal
	Amount       decimal.Decimal
}

// amount resolves the leg amount: explicit Amount when > 0, else distance × rate.
func (in MileageRouteInput) amount() decimal.Decimal {
	if in.Amount.GreaterThan(decimal.Zero) {
		return in.Amount
	}
	return in.Distance.Mul(in.Rate)
}

// ListMileageRoutes returns the mileage legs for a claim.
func (s *Service) ListMileageRoutes(ctx context.Context, tenantID, claimID uuid.UUID) ([]*ent.MileageRoute, error) {
	if err := s.claimBelongs(ctx, tenantID, claimID); err != nil {
		return nil, err
	}
	return s.orm.MileageRoute.Query().
		Where(mileageroute.TenantID(tenantID), mileageroute.ExpenseClaimID(claimID)).
		Order(ent.Asc(mileageroute.FieldCreatedAt)).All(ctx)
}

// CreateMileageRoute appends a mileage leg and re-totals the claim amount.
func (s *Service) CreateMileageRoute(ctx context.Context, tenantID, claimID uuid.UUID, in MileageRouteInput) (*ent.MileageRoute, error) {
	if err := s.claimBelongs(ctx, tenantID, claimID); err != nil {
		return nil, err
	}
	b := s.orm.MileageRoute.Create().
		SetTenantID(tenantID).
		SetExpenseClaimID(claimID).
		SetDistance(in.Distance).
		SetRate(in.Rate).
		SetAmount(in.amount())
	if in.RouteDate != nil {
		b = b.SetRouteDate(*in.RouteDate)
	}
	if in.FromLocation != "" {
		b = b.SetFromLocation(in.FromLocation)
	}
	if in.ToLocation != "" {
		b = b.SetToLocation(in.ToLocation)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("payroll: create mileage route: %w", err)
	}
	if err := s.recomputeClaimFromMileage(ctx, tenantID, claimID); err != nil {
		return row, err
	}
	return row, nil
}

// DeleteMileageRoute removes a mileage leg and re-totals the claim amount.
func (s *Service) DeleteMileageRoute(ctx context.Context, tenantID, claimID, routeID uuid.UUID) error {
	n, err := s.orm.MileageRoute.Delete().
		Where(mileageroute.ID(routeID), mileageroute.TenantID(tenantID), mileageroute.ExpenseClaimID(claimID)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("payroll: delete mileage route: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("payroll: mileage route not found")
	}
	return s.recomputeClaimFromMileage(ctx, tenantID, claimID)
}

// recomputeClaimFromMileage sets the claim amount to the sum of its mileage legs.
func (s *Service) recomputeClaimFromMileage(ctx context.Context, tenantID, claimID uuid.UUID) error {
	routes, err := s.orm.MileageRoute.Query().
		Where(mileageroute.TenantID(tenantID), mileageroute.ExpenseClaimID(claimID)).All(ctx)
	if err != nil {
		return fmt.Errorf("payroll: sum mileage routes: %w", err)
	}
	total := decimal.Zero
	for _, rt := range routes {
		total = total.Add(rt.Amount)
	}
	_, err = s.orm.ExpenseClaim.Update().
		Where(expenseclaim.ID(claimID), expenseclaim.TenantID(tenantID)).
		SetAmount(total).Save(ctx)
	if err != nil {
		return fmt.Errorf("payroll: retotal mileage claim: %w", err)
	}
	return nil
}

// SetClaimAttachment records the uploaded attachment relative path on a claim.
func (s *Service) SetClaimAttachment(ctx context.Context, tenantID, claimID uuid.UUID, rel string) (*ent.ExpenseClaim, error) {
	existing, err := s.GetClaim(ctx, tenantID, claimID)
	if err != nil {
		return nil, err
	}
	return existing.Update().SetAttachmentURL(rel).Save(ctx)
}
