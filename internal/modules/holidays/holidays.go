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

// ErrNotInherited is returned when switching a holiday that is not a platform one.
var ErrNotInherited = errors.New("platform holiday not found")

// Holiday is one holiday as a tenant sees it.
type Holiday struct {
	*ent.PublicHoliday
	// Inherited marks a platform holiday, which the tenant can only switch on or off.
	Inherited bool `json:"inherited"`
	Active    bool `json:"active"`
	// Key is the calendar rule a platform holiday comes from (new_year, labour_day, ...), the key
	// notifications-api greets customers by; empty for a tenant's own holiday or one added by hand.
	Key string `json:"key,omitempty"`
}

func off(ctx context.Context, c *ent.Client, tenantID uuid.UUID) ([]string, error) {
	row, err := c.AppSetting.Query().Where(appsetting.TenantID(tenantID), appsetting.AppKey(OffKey)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("holidays: load switched off: %w", err)
	}
	var ids []string
	if row.Value != "" {
		if err := json.Unmarshal([]byte(row.Value), &ids); err != nil {
			return nil, fmt.Errorf("holidays: decode switched off: %w", err)
		}
	}
	return ids, nil
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
	var hidden []string
	if len(tenants) > 1 {
		if hidden, err = off(ctx, c, tenantID); err != nil {
			return nil, err
		}
	}
	out := make([]Holiday, len(rows))
	for i, r := range rows {
		h := Holiday{PublicHoliday: r, Inherited: r.TenantID != tenantID}
		h.Active = !h.Inherited || !slices.Contains(hidden, r.ID.String())
		if h.Inherited || r.TenantID == system {
			h.Key = KeyOf(r.Name)
		}
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

// SetActive switches a platform holiday on or off for one tenant; switching it on again is the
// revert.
func SetActive(ctx context.Context, c *ent.Client, system, tenantID, id uuid.UUID, active bool) (*Holiday, error) {
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
	ids, err := off(ctx, c, tenantID)
	if err != nil {
		return nil, err
	}
	ids = slices.DeleteFunc(ids, func(s string) bool { return s == id.String() })
	if !active {
		ids = append(ids, id.String())
	}
	raw, err := json.Marshal(ids)
	if err != nil {
		return nil, err
	}
	err = c.AppSetting.Create().SetTenantID(tenantID).SetAppKey(OffKey).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).UpdateNewValues().Exec(ctx)
	if err != nil {
		return nil, fmt.Errorf("holidays: save: %w", err)
	}
	return &Holiday{PublicHoliday: row, Inherited: true, Active: active}, nil
}
