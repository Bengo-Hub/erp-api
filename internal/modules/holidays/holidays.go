// Package holidays resolves a tenant's public holidays: the platform's national ones, which every
// tenant inherits and may switch off one by one, and the tenant's own. Platform rows belong to the
// system tenant and are never copied.
package holidays

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/publicholiday"
)

// OffKey is the AppSetting key holding the ids of the platform holidays a tenant switched off.
const OffKey = "holidays.off"

// OffRulesKey is the AppSetting key holding the rule keys (labour_day, ...) a tenant switched off
// for every year, so next year's occurrence is off too without anyone switching it again.
const OffRulesKey = "holidays.off_rules"

// ErrNotInherited is returned when switching a holiday that is not a platform one.
var ErrNotInherited = errors.New("platform holiday not found")

// ErrNoRule is returned when a holiday is switched off for every year but has no yearly rule (one
// the platform owner added by hand); it can still be switched off for its own date.
var ErrNoRule = errors.New("this holiday has no yearly rule; switch it off for this date only")

// Holiday is one holiday as a tenant sees it.
type Holiday struct {
	*ent.PublicHoliday
	// Inherited marks a platform holiday, which the tenant can only switch on or off.
	Inherited bool `json:"inherited"`
	Active    bool `json:"active"`
	// Key is the calendar rule a platform holiday comes from (new_year, labour_day, ...), the key
	// notifications-api greets customers by; empty for a tenant's own holiday or one added by hand.
	Key string `json:"key,omitempty"`
	// OffEveryYear marks a platform holiday the tenant switched off for every year (by its rule).
	OffEveryYear bool `json:"off_every_year,omitempty"`
}

// off is a tenant's list stored under one AppSetting key (OffKey or OffRulesKey).
func off(ctx context.Context, c *ent.Client, tenantID uuid.UUID, key string) ([]string, error) {
	row, err := c.AppSetting.Query().Where(appsetting.TenantID(tenantID), appsetting.AppKey(key)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("holidays: load %s: %w", key, err)
	}
	var ids []string
	if row.Value != "" {
		if err := json.Unmarshal([]byte(row.Value), &ids); err != nil {
			return nil, fmt.Errorf("holidays: decode %s: %w", key, err)
		}
	}
	return ids, nil
}

func saveOff(ctx context.Context, c *ent.Client, tenantID uuid.UUID, key string, list []string) error {
	if list == nil {
		list = []string{}
	}
	raw, err := json.Marshal(list)
	if err != nil {
		return err
	}
	err = c.AppSetting.Create().SetTenantID(tenantID).SetAppKey(key).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).UpdateNewValues().Exec(ctx)
	if err != nil {
		return fmt.Errorf("holidays: save %s: %w", key, err)
	}
	return nil
}

// List returns the tenant's and the platform's holidays in [from, to), newest first. A zero bound
// is open.
func List(ctx context.Context, c *ent.Client, system, tenantID uuid.UUID, from, to time.Time) ([]Holiday, error) {
	tenants := []uuid.UUID{tenantID}
	if system != uuid.Nil && system != tenantID {
		tenants = append(tenants, system)
	}
	q := c.PublicHoliday.Query().Where(publicholiday.TenantIDIn(tenants...))
	if !from.IsZero() {
		q = q.Where(publicholiday.DateGTE(from))
	}
	if !to.IsZero() {
		q = q.Where(publicholiday.DateLT(to))
	}
	rows, err := q.Order(ent.Desc(publicholiday.FieldDate), ent.Asc(publicholiday.FieldName)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("holidays: list: %w", err)
	}
	var hidden, hiddenRules []string
	if len(tenants) > 1 {
		if hidden, err = off(ctx, c, tenantID, OffKey); err != nil {
			return nil, err
		}
		if hiddenRules, err = off(ctx, c, tenantID, OffRulesKey); err != nil {
			return nil, err
		}
	}
	out := make([]Holiday, len(rows))
	for i, r := range rows {
		h := Holiday{PublicHoliday: r, Inherited: r.TenantID != tenantID}
		if h.Inherited || r.TenantID == system {
			h.Key = KeyOf(r.Name)
		}
		h.OffEveryYear = h.Inherited && h.Key != "" && slices.Contains(hiddenRules, h.Key)
		h.Active = !h.Inherited || (!slices.Contains(hidden, r.ID.String()) && !h.OffEveryYear)
		out[i] = h
	}
	return out, nil
}

// Active returns the holidays that apply to the tenant in [from, to).
func Active(ctx context.Context, c *ent.Client, system, tenantID uuid.UUID, from, to time.Time) ([]*ent.PublicHoliday, error) {
	all, err := List(ctx, c, system, tenantID, from, to)
	if err != nil {
		return nil, err
	}
	out := make([]*ent.PublicHoliday, 0, len(all))
	for _, h := range all {
		if h.Active {
			out = append(out, h.PublicHoliday)
		}
	}
	return out, nil
}

// SetActive switches a platform holiday on or off for one tenant, for its own date or, with
// everyYear, for every year by its rule. Switching it on again is the revert of both.
func SetActive(ctx context.Context, c *ent.Client, system, tenantID, id uuid.UUID, active, everyYear bool) (*Holiday, error) {
	if system == uuid.Nil || system == tenantID {
		return nil, ErrNotInherited
	}
	row, err := c.PublicHoliday.Query().Where(publicholiday.ID(id), publicholiday.TenantID(system)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, ErrNotInherited
	}
	if err != nil {
		return nil, fmt.Errorf("holidays: load: %w", err)
	}
	key := KeyOf(row.Name)
	if !active && everyYear && key == "" {
		return nil, ErrNoRule
	}
	ids, err := off(ctx, c, tenantID, OffKey)
	if err != nil {
		return nil, err
	}
	rules, err := off(ctx, c, tenantID, OffRulesKey)
	if err != nil {
		return nil, err
	}
	ids = slices.DeleteFunc(ids, func(s string) bool { return s == id.String() })
	if !active && !everyYear {
		ids = append(ids, id.String())
	}
	// Switching any occurrence on again ends "every year" for its rule; the other years' own
	// switches (by id) stay as they were.
	hadRule := slices.Contains(rules, key)
	rules = slices.DeleteFunc(rules, func(s string) bool { return key != "" && s == key })
	if !active && everyYear {
		rules = append(rules, key)
	}
	if err := saveOff(ctx, c, tenantID, OffKey, ids); err != nil {
		return nil, err
	}
	if hadRule || (!active && everyYear) {
		if err := saveOff(ctx, c, tenantID, OffRulesKey, rules); err != nil {
			return nil, err
		}
	}
	return &Holiday{PublicHoliday: row, Inherited: true, Active: active, Key: key, OffEveryYear: !active && everyYear}, nil
}
