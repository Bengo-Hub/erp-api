// Package inherited holds the pieces every inherit and customise setting shares: the name match
// that lets a company's own row take the place of a platform row, and the per-company override
// records (an AppSetting per kind, keyed by the platform row's id, holding only changed fields).
package inherited

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
)

// NameKey is how a company's own row is matched to a platform row: case and spaces ignored.
func NameKey(name string) string { return strings.ToLower(strings.TrimSpace(name)) }

// Tenants is the company plus the platform tenant: the rows a company can read.
func Tenants(system, tenantID uuid.UUID) []uuid.UUID {
	if system == uuid.Nil || system == tenantID {
		return []uuid.UUID{tenantID}
	}
	return []uuid.UUID{tenantID, system}
}

// Load reads a company's override records of one kind.
func Load[T any](ctx context.Context, c *ent.Client, tenantID uuid.UUID, key string) (map[string]T, error) {
	out := map[string]T{}
	row, err := c.AppSetting.Query().Where(appsetting.TenantID(tenantID), appsetting.AppKey(key)).Only(ctx)
	if ent.IsNotFound(err) {
		return out, nil
	}
	if err != nil {
		return nil, fmt.Errorf("load %s: %w", key, err)
	}
	if row.Value != "" {
		if err := json.Unmarshal([]byte(row.Value), &out); err != nil {
			return nil, fmt.Errorf("decode %s: %w", key, err)
		}
	}
	return out, nil
}

// Save stores a company's override records of one kind.
func Save[T any](ctx context.Context, c *ent.Client, tenantID uuid.UUID, key string, m map[string]T) error {
	raw, err := json.Marshal(m)
	if err != nil {
		return err
	}
	err = c.AppSetting.Create().SetTenantID(tenantID).SetAppKey(key).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).UpdateNewValues().Exec(ctx)
	if err != nil {
		return fmt.Errorf("save %s: %w", key, err)
	}
	return nil
}
