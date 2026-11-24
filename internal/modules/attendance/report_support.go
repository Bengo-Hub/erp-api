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
	exp, err := s.ExpectedStarts(ctx, tenantID, day, empIDs)
	if err != nil {
		return nil, err
	}
	out := make([]uuid.UUID, 0, len(exp))
	for id := range exp {
		out = append(out, id)
	}
	return out, nil
}

// ExpectedStarts is ExpectedToWork with, for each person, the instant after which a missing
// clock-in counts as absent rather than "not in yet": the shift start plus grace in the
// company zone. A zero time means the shift has no start time (count as due at once).
func (s *Service) ExpectedStarts(ctx context.Context, tenantID uuid.UUID, day time.Time, empIDs []uuid.UUID) (map[uuid.UUID]time.Time, error) {
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
	d := dateOnly(day)
	expected, shifts, err := s.expectedToWork(ctx, tenantID, ids, d, st)
	if err != nil || len(expected) == 0 {
		return nil, err
	}
	loc := s.TenantZone(ctx, tenantID)
	out := make(map[uuid.UUID]time.Time, len(expected))
	for _, id := range expected {
		var due time.Time
		if ds := shifts[empDay{id, d}]; ds.Start != "" {
			if at, ok := clockOn(d, ds.Start, loc); ok {
				due = at.Add(time.Duration(ds.Grace) * time.Minute)
			}
		}
		out[id] = due
	}
	return out, nil
}

// TenantZone is the tenant's company zone (Africa/Nairobi when unset).
func (s *Service) TenantZone(ctx context.Context, tenantID uuid.UUID) *time.Location {
	if z, err := s.loadZones(ctx, tenantID); err == nil {
		return z.For()
	}
	loc, _ := time.LoadLocation(defaultZone)
	return loc
}
