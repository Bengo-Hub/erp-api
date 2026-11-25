// Package tenantref checks that record ids sent by a client belong to the caller's tenant before
// they are stored or used. An id of another tenant answers exactly like one that does not exist.
package tenantref

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
)

// ErrNotFound is returned when an id is not one of the tenant's records.
var ErrNotFound = errors.New("not found")

// Exists is any ent query builder's Exist.
type Exists interface {
	Exist(ctx context.Context) (bool, error)
}

// Require answers "<what> not found" unless the tenant-scoped query finds a row.
func Require(ctx context.Context, what string, q Exists) error {
	ok, err := q.Exist(ctx)
	if err != nil {
		return fmt.Errorf("check %s: %w", what, err)
	}
	if !ok {
		return fmt.Errorf("%s %w", what, ErrNotFound)
	}
	return nil
}

// Employee requires an optional id (nil passes) to be an employee of the tenant.
func Employee(ctx context.Context, orm *ent.Client, tenantID uuid.UUID, what string, id *uuid.UUID) error {
	if id == nil {
		return nil
	}
	return Require(ctx, what, orm.Employee.Query().Where(employee.TenantID(tenantID), employee.ID(*id)))
}
