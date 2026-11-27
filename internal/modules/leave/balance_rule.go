package leave

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaveentitlement"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
)

// What happens to a request for more days than the person has left.
const (
	BalanceRefuse = "refuse"
	BalanceAllow  = "allow"
)

// BalanceRulesKey is the AppSetting key holding a tenant's balance rule per leave type, stored
// like the count modes (only changed types, keyed by category id).
const BalanceRulesKey = "leave.balance_rules"

// ErrBalanceRule is returned for an unknown rule.
var ErrBalanceRule = errors.New("balance rule must be refuse or allow")

// BalanceError refuses a request that exceeds the balance.
type BalanceError struct{ Message string }

func (e *BalanceError) Error() string { return e.Message }

// typeSettings loads a per leave type setting (category id to value).
func typeSettings(ctx context.Context, c *ent.Client, tenantID uuid.UUID, key string) (map[string]string, error) {
	out := map[string]string{}
	row, err := c.AppSetting.Query().Where(appsetting.TenantID(tenantID), appsetting.AppKey(key)).Only(ctx)
	if ent.IsNotFound(err) {
		return out, nil
	}
	if err != nil {
		return nil, fmt.Errorf("leave: load %s: %w", key, err)
	}
	if row.Value != "" {
		if err := json.Unmarshal([]byte(row.Value), &out); err != nil {
			return nil, fmt.Errorf("leave: decode %s: %w", key, err)
		}
	}
	return out, nil
}

// saveTypeSetting stores one leave type's value for the tenant. The type may be one it inherits.
func (s *Service) saveTypeSetting(ctx context.Context, tenantID, categoryID uuid.UUID, key, value string) (*CategoryView, error) {
	cat, err := s.usableCategory(ctx, tenantID, categoryID)
	if err != nil {
		return nil, err
	}
	m, err := typeSettings(ctx, s.orm, tenantID, key)
	if err != nil {
		return nil, err
	}
	m[categoryID.String()] = value
	raw, err := json.Marshal(m)
	if err != nil {
		return nil, err
	}
	err = s.orm.AppSetting.Create().
		SetTenantID(tenantID).SetAppKey(key).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).
		UpdateNewValues().Exec(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: save %s: %w", key, err)
	}
	views, err := s.CategoryViews(ctx, tenantID, []*ent.LeaveCategory{cat})
	if err != nil {
		return nil, err
	}
	return &views[0], nil
}

// SetBalanceRule stores whether a leave type refuses requests beyond the balance.
func (s *Service) SetBalanceRule(ctx context.Context, tenantID, categoryID uuid.UUID, rule string) (*CategoryView, error) {
	if rule != BalanceRefuse && rule != BalanceAllow {
		return nil, ErrBalanceRule
	}
	return s.saveTypeSetting(ctx, tenantID, categoryID, BalanceRulesKey, rule)
}

// ruleOf is the tenant's rule, else refuse for a paid type and allow for an unpaid one.
func ruleOf(rules map[string]string, c *ent.LeaveCategory) string {
	if r := rules[c.ID.String()]; r == BalanceRefuse || r == BalanceAllow {
		return r
	}
	if c.IsPaid {
		return BalanceRefuse
	}
	return BalanceAllow
}

// balanceCheck is a request held against the balance of its type and year.
type balanceCheck struct {
	Rule      string
	Remaining *decimal.Decimal // nil: no balance set up
	Pending   decimal.Decimal
	Available *decimal.Decimal
	Over      bool
	Message   string
}

// refusal is the error for a request the rule refuses, else nil.
func (b balanceCheck) refusal() error {
	if b.Over && b.Rule == BalanceRefuse {
		return &BalanceError{b.Message}
	}
	return nil
}

// checkBalance compares days with the remaining balance less the person's pending requests of
// the same type and year. withPending is false at approval, where only the request itself counts.
// No balance row means no limit.
func (s *Service) checkBalance(ctx context.Context, c *ent.Client, tenantID, employeeID uuid.UUID, cat *ent.LeaveCategory, year int, days decimal.Decimal, withPending bool) (balanceCheck, error) {
	return s.checkBalanceExcluding(ctx, c, tenantID, employeeID, cat, year, days, withPending, uuid.Nil)
}

// checkBalanceExcluding is checkBalance without one pending request (the one being edited) among
// the pending days.
func (s *Service) checkBalanceExcluding(ctx context.Context, c *ent.Client, tenantID, employeeID uuid.UUID, cat *ent.LeaveCategory, year int, days decimal.Decimal, withPending bool, excluding uuid.UUID) (balanceCheck, error) {
	var out balanceCheck
	rules, err := typeSettings(ctx, c, tenantID, BalanceRulesKey)
	if err != nil {
		return out, err
	}
	out.Rule = ruleOf(rules, cat)
	bal, err := c.LeaveBalance.Query().Where(
		leavebalance.TenantID(tenantID), leavebalance.EmployeeID(employeeID),
		leavebalance.CategoryID(cat.ID), leavebalance.Year(year)).First(ctx)
	if ent.IsNotFound(err) {
		return out, nil
	}
	if err != nil {
		return out, fmt.Errorf("leave: load balance: %w", err)
	}
	// Approving leave with no balance records the days taken on a row with nothing entitled. For
	// an inherited type that accrual does not cover, that row is not a balance anyone set up.
	if bal.DaysEntitled.IsZero() && cat.TenantID != tenantID {
		set, err := c.LeaveEntitlement.Query().Where(
			leaveentitlement.TenantID(tenantID), leaveentitlement.EmployeeID(employeeID),
			leaveentitlement.CategoryID(cat.ID), leaveentitlement.Year(year)).Exist(ctx)
		if err != nil {
			return out, fmt.Errorf("leave: load entitlement: %w", err)
		}
		if !set {
			return out, nil
		}
	}
	remaining := bal.DaysRemaining
	out.Remaining = &remaining
	if withPending {
		from := time.Date(year, 1, 1, 0, 0, 0, 0, time.UTC)
		rows, err := c.LeaveRequest.Query().Where(
			leaverequest.TenantID(tenantID), leaverequest.EmployeeID(employeeID),
			leaverequest.CategoryID(cat.ID), leaverequest.StatusEQ(leaverequest.StatusPending),
			leaverequest.StartDateGTE(from), leaverequest.StartDateLT(from.AddDate(1, 0, 0)),
			leaverequest.IDNEQ(excluding)).All(ctx)
		if err != nil {
			return out, fmt.Errorf("leave: load pending requests: %w", err)
		}
		for _, r := range rows {
			out.Pending = out.Pending.Add(r.DaysRequested)
		}
	}
	available := remaining.Sub(out.Pending)
	out.Available = &available
	if out.Over = days.GreaterThan(available); out.Over {
		out.Message = fmt.Sprintf("this request takes %s days of %s but only %s of the %d balance are available",
			days, cat.Name, decimal.Max(available, decimal.Zero), year)
		if out.Pending.IsPositive() {
			out.Message += fmt.Sprintf(" (%s remaining, %s already in pending requests)", remaining, out.Pending)
		}
	}
	return out, nil
}

// refuseOverBalance is the balance check of an existing pending request, made again at approval.
func (s *Service) refuseOverBalance(ctx context.Context, c *ent.Client, tenantID uuid.UUID, req *ent.LeaveRequest) error {
	cat, err := c.LeaveCategory.Query().Where(leavecategory.ID(req.CategoryID),
		leavecategory.TenantIDIn(tenantID, s.systemTenant)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil // the leave type was deleted: there is no rule left to apply
	}
	if err != nil {
		return fmt.Errorf("leave: load leave type: %w", err)
	}
	if cat, err = s.withChanges(ctx, c, tenantID, cat); err != nil {
		return err
	}
	chk, err := s.checkBalance(ctx, c, tenantID, req.EmployeeID, cat, req.StartDate.Year(), req.DaysRequested, false)
	if err != nil {
		return err
	}
	return chk.refusal()
}
