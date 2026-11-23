package attendance

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/authoutlet"
	"github.com/Bengo-Hub/erp-api/internal/ent/companysettings"
)

// tenantZones resolves the time zone for an outlet of one tenant: the outlet's own zone, else
// the company zone, else Africa/Nairobi. Loaded once per request or batch (two queries).
type tenantZones struct {
	fallback *time.Location
	outlets  map[uuid.UUID]*time.Location
}

// loadZones reads the company zone and every outlet zone of the tenant.
func (s *Service) loadZones(ctx context.Context, tenantID uuid.UUID) (*tenantZones, error) {
	z := &tenantZones{outlets: map[uuid.UUID]*time.Location{}}
	z.fallback, _ = time.LoadLocation(defaultZone)
	cs, err := s.orm.CompanySettings.Query().Where(companysettings.TenantID(tenantID)).First(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return nil, err
	}
	if cs != nil && cs.Timezone != "" {
		if loc, lerr := time.LoadLocation(cs.Timezone); lerr == nil {
			z.fallback = loc
		}
	}
	outlets, err := s.orm.AuthOutlet.Query().Where(authoutlet.TenantID(tenantID)).
		Select(authoutlet.FieldID, authoutlet.FieldTimezone).All(ctx)
	if err != nil {
		return nil, err
	}
	for _, o := range outlets {
		if o.Timezone == "" {
			continue
		}
		if loc, lerr := time.LoadLocation(o.Timezone); lerr == nil {
			z.outlets[o.ID] = loc
		}
	}
	return z, nil
}

// For returns the zone of the first outlet given that has one, else the tenant zone.
func (z *tenantZones) For(outletIDs ...*uuid.UUID) *time.Location {
	for _, id := range outletIDs {
		if id == nil {
			continue
		}
		if loc, ok := z.outlets[*id]; ok {
			return loc
		}
	}
	return z.fallback
}

// Named returns the named IANA zone when it loads, else the outlet chain of For.
func (z *tenantZones) Named(name string, outletIDs ...*uuid.UUID) *time.Location {
	if name != "" {
		if loc, err := time.LoadLocation(name); err == nil {
			return loc
		}
	}
	return z.For(outletIDs...)
}
