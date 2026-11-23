package attendance

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
)

// Helpers the reports module uses, so attendance rules (who is expected to work, how a door
// event is described) live in one place.

// AccessReason is the access log label for a door event.
func AccessReason(e *ent.AccessEvent) string { return accessReason(e) }

// ExpectedToWork returns the active employees planned to work on day (shift, roster and
// override aware, public holidays excluded), optionally narrowed to empIDs.
func (s *Service) ExpectedToWork(ctx context.Context, tenantID uuid.UUID, day time.Time, empIDs []uuid.UUID) ([]uuid.UUID, error) {
	st, err := s.GetSettings(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	q := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.Deleted(false), employee.Terminated(false))
	if len(empIDs) > 0 {
		q = q.Where(employee.IDIn(empIDs...))
	}
	ids, err := q.IDs(ctx)
	if err != nil || len(ids) == 0 {
		return nil, err
	}
	return s.expectedToWork(ctx, tenantID, ids, dateOnly(day), st)
}

// TenantZone is the tenant's company zone (Africa/Nairobi when unset).
func (s *Service) TenantZone(ctx context.Context, tenantID uuid.UUID) *time.Location {
	if z, err := s.loadZones(ctx, tenantID); err == nil {
		return z.For()
	}
	loc, _ := time.LoadLocation(defaultZone)
	return loc
}
