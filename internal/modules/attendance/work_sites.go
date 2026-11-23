package attendance

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/Bengo-Hub/httpware/geo"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/worksite"
)

// ErrWorkSiteNotFound is returned for a site outside the tenant.
var ErrWorkSiteNotFound = errors.New("attendance: work site not found")

// WorkSiteInput is the create/patch payload; nil fields stay unchanged on patch.
type WorkSiteInput struct {
	Name     *string
	OutletID *uuid.UUID
	Center   *geo.Point
	RadiusM  *float64
	Ring     *[][]float64
	Holes    *[][][]float64
	Active   *bool
}

// fenceOf is the site's geo-fence.
func fenceOf(w *ent.WorkSite) geo.Fence {
	return geo.Fence{Center: geo.Point{Lat: w.CenterLat, Lng: w.CenterLng}, RadiusM: w.RadiusM, Ring: w.Ring, Holes: w.Holes}
}

// validateSite checks the resulting fence is usable.
func validateSite(name string, f geo.Fence) error {
	if strings.TrimSpace(name) == "" {
		return errors.New("name is required")
	}
	if len(f.Ring) > 0 && len(f.Ring) < 3 {
		return errors.New("ring needs at least 3 points")
	}
	for _, pt := range f.Ring {
		if len(pt) != 2 || !geo.Valid(geo.Point{Lat: pt[1], Lng: pt[0]}) {
			return errors.New("ring points must be [lng, lat] pairs")
		}
	}
	if !f.Usable() {
		return errors.New("set a center with a radius above 0, or a ring")
	}
	return nil
}

// ListWorkSites returns the tenant's work sites (active only when activeOnly).
func (s *Service) ListWorkSites(ctx context.Context, tenantID uuid.UUID, activeOnly bool) ([]*ent.WorkSite, error) {
	q := s.orm.WorkSite.Query().Where(worksite.TenantID(tenantID))
	if activeOnly {
		q = q.Where(worksite.Active(true))
	}
	return q.Order(ent.Asc(worksite.FieldName)).All(ctx)
}

// CreateWorkSite adds a geo-fenced work site.
func (s *Service) CreateWorkSite(ctx context.Context, tenantID uuid.UUID, in WorkSiteInput) (*ent.WorkSite, error) {
	w := &ent.WorkSite{RadiusM: 0, Active: true}
	applySite(w, in)
	if err := validateSite(w.Name, fenceOf(w)); err != nil {
		return nil, err
	}
	row, err := s.orm.WorkSite.Create().SetTenantID(tenantID).SetName(strings.TrimSpace(w.Name)).
		SetNillableOutletID(w.OutletID).SetCenterLat(w.CenterLat).SetCenterLng(w.CenterLng).
		SetRadiusM(w.RadiusM).SetRing(w.Ring).SetHoles(w.Holes).SetActive(w.Active).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create work site: %w", err)
	}
	return row, nil
}

// UpdateWorkSite patches a tenant work site.
func (s *Service) UpdateWorkSite(ctx context.Context, tenantID, id uuid.UUID, in WorkSiteInput) (*ent.WorkSite, error) {
	w, err := s.orm.WorkSite.Query().Where(worksite.TenantID(tenantID), worksite.ID(id)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, ErrWorkSiteNotFound
	}
	if err != nil {
		return nil, err
	}
	applySite(w, in)
	if err := validateSite(w.Name, fenceOf(w)); err != nil {
		return nil, err
	}
	return w.Update().SetName(strings.TrimSpace(w.Name)).SetNillableOutletID(w.OutletID).
		SetCenterLat(w.CenterLat).SetCenterLng(w.CenterLng).SetRadiusM(w.RadiusM).
		SetRing(w.Ring).SetHoles(w.Holes).SetActive(w.Active).Save(ctx)
}

func applySite(w *ent.WorkSite, in WorkSiteInput) {
	if in.Name != nil {
		w.Name = *in.Name
	}
	if in.OutletID != nil {
		w.OutletID = in.OutletID
	}
	if in.Center != nil {
		w.CenterLat, w.CenterLng = in.Center.Lat, in.Center.Lng
	}
	if in.RadiusM != nil {
		w.RadiusM = *in.RadiusM
	}
	if in.Ring != nil {
		w.Ring = *in.Ring
	}
	if in.Holes != nil {
		w.Holes = *in.Holes
	}
	if in.Active != nil {
		w.Active = *in.Active
	}
}

// DeleteWorkSite removes a tenant work site.
func (s *Service) DeleteWorkSite(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.WorkSite.Delete().Where(worksite.TenantID(tenantID), worksite.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("attendance: delete work site: %w", err)
	}
	if n == 0 {
		return ErrWorkSiteNotFound
	}
	return nil
}

// sitesFor returns the active sites an employee clocks in at: those of their outlet and those
// with no outlet, or every active site when that leaves none.
func (s *Service) sitesFor(ctx context.Context, tenantID uuid.UUID, outlet *uuid.UUID) ([]*ent.WorkSite, error) {
	all, err := s.ListWorkSites(ctx, tenantID, true)
	if err != nil || outlet == nil {
		return all, err
	}
	var mine []*ent.WorkSite
	for _, w := range all {
		if w.OutletID == nil || *w.OutletID == *outlet {
			mine = append(mine, w)
		}
	}
	if len(mine) == 0 {
		return all, nil
	}
	return mine, nil
}
