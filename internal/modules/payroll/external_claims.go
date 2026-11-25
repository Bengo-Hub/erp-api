package payroll

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"
	"time"

	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/expenseclaim"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
)

// Claims raised by other services. ERP owns per diem rates, eligibility, tax treatment and
// approval; a caller such as logistics-api only reports what happened (a staff driver spent
// N days on a regional trip of D km) and gets back a normal expense claim that goes through
// the usual approve, schedule-to-payroll and reimburse flow.

// PerDiemPolicyKey is the AppSetting key holding a tenant's per diem policy.
const PerDiemPolicyKey = "hrm.per_diem_policy"

// PerDiemPolicy is the tenant's per diem rule set, edited in erp-ui HR settings.
type PerDiemPolicy struct {
	Enabled bool `json:"enabled"`
	// DailyRate applies when the employee's job group has no rate of its own.
	DailyRate decimal.Decimal `json:"daily_rate"`
	// JobGroupRates maps a job group id to its daily rate (senior grades often get more).
	JobGroupRates map[string]decimal.Decimal `json:"job_group_rates,omitempty"`
	// MinDistanceKm is the trip distance below which no per diem is due (in-town work).
	MinDistanceKm float64 `json:"min_distance_km"`
	// MaxDays caps the days on one claim. 0 means no cap.
	MaxDays int `json:"max_days,omitempty"`
	// AutoApprove approves external per diem claims on creation. Off by default so HR
	// reviews each one.
	AutoApprove bool `json:"auto_approve,omitempty"`
}

// DefaultPerDiemPolicy is returned for tenants that never saved one: disabled, so no claim
// is raised until HR sets a rate.
func DefaultPerDiemPolicy() PerDiemPolicy {
	return PerDiemPolicy{MinDistanceKm: 50}
}

// Validate checks a policy before it is saved.
func (p PerDiemPolicy) Validate() error {
	if p.DailyRate.IsNegative() {
		return errors.New("daily_rate cannot be negative")
	}
	if p.Enabled && !p.DailyRate.IsPositive() && len(p.JobGroupRates) == 0 {
		return errors.New("set a daily_rate or job group rates before enabling per diem")
	}
	for id, r := range p.JobGroupRates {
		if _, err := uuid.Parse(id); err != nil {
			return fmt.Errorf("job_group_rates: %q is not a job group id", id)
		}
		if r.IsNegative() {
			return errors.New("job group rates cannot be negative")
		}
	}
	if p.MinDistanceKm < 0 || p.MaxDays < 0 {
		return errors.New("min_distance_km and max_days cannot be negative")
	}
	return nil
}

// GetPerDiemPolicy returns the tenant's per diem policy, or the default.
func (s *Service) GetPerDiemPolicy(ctx context.Context, tenantID uuid.UUID) (PerDiemPolicy, error) {
	row, err := s.orm.AppSetting.Query().
		Where(appsetting.TenantID(tenantID), appsetting.AppKey(PerDiemPolicyKey)).
		Only(ctx)
	if ent.IsNotFound(err) {
		return DefaultPerDiemPolicy(), nil
	}
	if err != nil {
		return PerDiemPolicy{}, fmt.Errorf("payroll: load per diem policy: %w", err)
	}
	p := DefaultPerDiemPolicy()
	if err := json.Unmarshal([]byte(row.Value), &p); err != nil {
		return PerDiemPolicy{}, fmt.Errorf("payroll: decode per diem policy: %w", err)
	}
	return p, nil
}

// SavePerDiemPolicy validates and stores the tenant's per diem policy.
func (s *Service) SavePerDiemPolicy(ctx context.Context, tenantID uuid.UUID, p PerDiemPolicy) (PerDiemPolicy, error) {
	if err := p.Validate(); err != nil {
		return PerDiemPolicy{}, err
	}
	raw, err := json.Marshal(p)
	if err != nil {
		return PerDiemPolicy{}, err
	}
	err = s.orm.AppSetting.Create().
		SetTenantID(tenantID).
		SetAppKey(PerDiemPolicyKey).
		SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).
		UpdateNewValues().
		Exec(ctx)
	if err != nil {
		return PerDiemPolicy{}, fmt.Errorf("payroll: save per diem policy: %w", err)
	}
	return p, nil
}

// External claim errors, mapped to HTTP statuses by the handler.
var (
	ErrNotAnEmployee   = errors.New("payroll: user is not an employee of this tenant")
	ErrPerDiemDisabled = errors.New("payroll: per diem is not enabled for this tenant")
	ErrNotEligible     = errors.New("payroll: trip is below the per diem distance threshold")
)

// ExternalClaimInput is what another service reports. For per_diem the amount is computed
// here from the policy; other claim types (fuel, reimbursement) carry an explicit amount.
type ExternalClaimInput struct {
	AuthUserID  uuid.UUID
	Source      string // calling service, e.g. "logistics"
	SourceKey   string // idempotency key, unique per tenant
	ClaimType   string // per_diem | reimbursement | other
	Days        float64
	Amount      decimal.Decimal
	DistanceKm  float64
	StartedAt   *time.Time
	EndedAt     *time.Time
	Description string
	Reference   map[string]any // caller ids (task, trip, destination) kept for audit
}

// ExternalClaimResult reports the claim and whether this call created it.
type ExternalClaimResult struct {
	Claim   *ent.ExpenseClaim
	Created bool
}

// tripDays derives whole days from the trip window: any part of a day counts, minimum one.
func tripDays(start, end *time.Time) float64 {
	if start == nil || end == nil || !end.After(*start) {
		return 1
	}
	return math.Max(1, math.Ceil(end.Sub(*start).Hours()/24))
}

// FindExternalClaim returns the claim already raised for a source key, if any.
func (s *Service) FindExternalClaim(ctx context.Context, tenantID uuid.UUID, sourceKey string) (*ent.ExpenseClaim, error) {
	c, err := s.orm.ExpenseClaim.Query().
		Where(
			expenseclaim.TenantID(tenantID),
			expenseclaim.DeleteStatus(false),
			metadataHas("source_key", sourceKey),
		).
		First(ctx)
	if ent.IsNotFound(err) {
		return nil, nil
	}
	return c, err
}

// metadataHas matches claims whose metadata contains key=value (jsonb containment).
func metadataHas(key, value string) func(*entsql.Selector) {
	raw, _ := json.Marshal(map[string]string{key: value})
	return func(sel *entsql.Selector) {
		sel.Where(entsql.P(func(b *entsql.Builder) {
			b.WriteString(sel.C(expenseclaim.FieldMetadata))
			b.WriteString(" @> ")
			b.Arg(string(raw))
			b.WriteString("::jsonb")
		}))
	}
}

// CreateExternalClaim raises (or returns the already raised) claim for a source key. The
// idempotency key row is written in the same transaction as the claim, so two concurrent
// calls with the same key cannot both create one.
func (s *Service) CreateExternalClaim(ctx context.Context, tenantID uuid.UUID, in ExternalClaimInput) (*ExternalClaimResult, error) {
	in.SourceKey = strings.TrimSpace(in.SourceKey)
	in.Source = strings.TrimSpace(in.Source)
	if in.SourceKey == "" || in.Source == "" {
		return nil, errors.New("payroll: source and source_key are required")
	}
	if in.AuthUserID == uuid.Nil {
		return nil, errors.New("payroll: auth_user_id is required")
	}
	claimType := strings.ToLower(strings.TrimSpace(in.ClaimType))
	if claimType == "" {
		claimType = "per_diem"
	}
	switch claimType {
	case "per_diem", "reimbursement", "other":
	default:
		return nil, fmt.Errorf("payroll: unsupported claim_type %q", claimType)
	}

	if existing, err := s.FindExternalClaim(ctx, tenantID, in.SourceKey); err != nil {
		return nil, fmt.Errorf("payroll: check existing claim: %w", err)
	} else if existing != nil {
		return &ExternalClaimResult{Claim: existing}, nil
	}

	emp, err := s.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.UserID(in.AuthUserID), employee.Deleted(false)).
		First(ctx)
	if ent.IsNotFound(err) {
		return nil, ErrNotAnEmployee
	}
	if err != nil {
		return nil, fmt.Errorf("payroll: resolve employee: %w", err)
	}

	amount := in.Amount
	days := in.Days
	var rate decimal.Decimal
	autoApprove := false
	if claimType == "per_diem" {
		policy, err := s.GetPerDiemPolicy(ctx, tenantID)
		if err != nil {
			return nil, err
		}
		if !policy.Enabled {
			return nil, ErrPerDiemDisabled
		}
		if in.DistanceKm > 0 && in.DistanceKm < policy.MinDistanceKm {
			return nil, ErrNotEligible
		}
		if days <= 0 {
			days = tripDays(in.StartedAt, in.EndedAt)
		}
		if policy.MaxDays > 0 && days > float64(policy.MaxDays) {
			days = float64(policy.MaxDays)
		}
		rate = s.perDiemRate(ctx, tenantID, emp.ID, policy)
		if !rate.IsPositive() {
			return nil, ErrPerDiemDisabled
		}
		amount = rate.Mul(decimal.NewFromFloat(days)).Round(2)
		autoApprove = policy.AutoApprove
	} else if !amount.IsPositive() {
		return nil, errors.New("payroll: amount is required for this claim type")
	}

	meta := map[string]any{
		"source":     in.Source,
		"source_key": in.SourceKey,
	}
	if days > 0 {
		meta["days"] = days
	}
	if rate.IsPositive() {
		meta["daily_rate"] = rate.StringFixed(2)
	}
	if in.DistanceKm > 0 {
		meta["distance_km"] = math.Round(in.DistanceKm*10) / 10
	}
	if in.StartedAt != nil {
		meta["started_at"] = in.StartedAt.UTC().Format(time.RFC3339)
	}
	if in.EndedAt != nil {
		meta["ended_at"] = in.EndedAt.UTC().Format(time.RFC3339)
	}
	if len(in.Reference) > 0 {
		meta["reference"] = in.Reference
	}

	appDate := time.Now()
	if in.EndedAt != nil {
		appDate = *in.EndedAt
	}
	description := strings.TrimSpace(in.Description)
	if description == "" {
		description = fmt.Sprintf("%s claim from %s", strings.ReplaceAll(claimType, "_", " "), in.Source)
	}

	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, err
	}
	rollback := func(e error) (*ExternalClaimResult, error) {
		_ = tx.Rollback()
		return nil, e
	}
	if _, err := tx.IdempotencyKey.Create().
		SetKey(fmt.Sprintf("claim:%s:%s", tenantID, in.SourceKey)).
		SetScope("payroll.external_claim").
		SetTenantID(tenantID).
		Save(ctx); err != nil {
		if ent.IsConstraintError(err) {
			_ = tx.Rollback()
			// A concurrent call won the race: return its claim.
			c, ferr := s.FindExternalClaim(ctx, tenantID, in.SourceKey)
			if ferr != nil || c == nil {
				return nil, fmt.Errorf("payroll: claim %s is being created", in.SourceKey)
			}
			return &ExternalClaimResult{Claim: c}, nil
		}
		return rollback(fmt.Errorf("payroll: idempotency key: %w", err))
	}
	b := tx.ExpenseClaim.Create().
		SetTenantID(tenantID).
		SetEmployeeID(emp.ID).
		SetAmount(amount).
		SetClaimType(claimType).
		SetCategory("Other").
		SetApplicationDate(appDate).
		SetMetadata(meta)
	if autoApprove {
		b = b.SetApproved(true)
	}
	c, err := b.Save(ctx)
	if err != nil {
		return rollback(fmt.Errorf("payroll: create claim: %w", err))
	}
	if days > 0 && rate.IsPositive() {
		description = fmt.Sprintf("%s (%s day(s) at %s)", description,
			decimal.NewFromFloat(days).String(), rate.StringFixed(2))
	}
	line := tx.ClaimItem.Create().
		SetTenantID(tenantID).
		SetExpenseClaimID(c.ID).
		SetDescription(description).
		SetAmount(amount)
	if _, err := line.Save(ctx); err != nil {
		return rollback(fmt.Errorf("payroll: create claim line: %w", err))
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}

	s.publishClaimBestEffort(ctx, tenantID, c.ID, "expense_claim.created", claimPayload(c))
	if autoApprove {
		s.publishClaimBestEffort(ctx, tenantID, c.ID, "expense_claim.approved", claimPayload(c))
	}
	return &ExternalClaimResult{Claim: c, Created: true}, nil
}

// perDiemRate picks the employee's job group rate, falling back to the policy's daily rate.
func (s *Service) perDiemRate(ctx context.Context, tenantID, employeeID uuid.UUID, p PerDiemPolicy) decimal.Decimal {
	if len(p.JobGroupRates) > 0 {
		sd, err := s.orm.SalaryDetails.Query().
			Where(salarydetails.TenantID(tenantID), salarydetails.EmployeeID(employeeID)).
			Order(ent.Desc(salarydetails.FieldIsActive), ent.Desc(salarydetails.FieldCreatedAt)).First(ctx)
		if err == nil && sd.JobGroupID != nil {
			if r, ok := p.JobGroupRates[sd.JobGroupID.String()]; ok && r.IsPositive() {
				return r
			}
		}
	}
	return p.DailyRate
}
