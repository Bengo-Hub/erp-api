package usersync

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/authoutlet"
	"github.com/Bengo-Hub/erp-api/internal/ent/authtenant"
)

// TenantSyncer upserts AuthTenant / AuthOutlet shadows. It provides the just-in-time shadow
// provisioning used by the auth.tenant.* / auth.outlet.* consumers. Auth-api is the source of truth; we only mirror the minimal reference.
type TenantSyncer struct {
	orm *ent.Client
	log *zap.Logger
}

func NewTenantSyncer(orm *ent.Client, log *zap.Logger) *TenantSyncer {
	return &TenantSyncer{orm: orm, log: log.Named("usersync.TenantSyncer")}
}

// TenantInput is the minimal data needed to upsert a tenant shadow.
type TenantInput struct {
	ID         uuid.UUID
	Slug       string
	Name       string
	Status     string
	IsPlatform bool
}

// UpsertTenant creates or updates the local AuthTenant shadow keyed on the auth-api UUID.
func (s *TenantSyncer) UpsertTenant(ctx context.Context, in TenantInput) (*ent.AuthTenant, error) {
	if in.ID == uuid.Nil {
		return nil, fmt.Errorf("usersync: empty tenant id")
	}
	if in.Status == "" {
		in.Status = "active"
	}
	now := time.Now().UTC()

	existing, err := s.orm.AuthTenant.Get(ctx, in.ID)
	if ent.IsNotFound(err) {
		return s.orm.AuthTenant.Create().
			SetID(in.ID).
			SetSlug(in.Slug).
			SetName(in.Name).
			SetStatus(in.Status).
			SetIsPlatform(in.IsPlatform).
			SetSyncedAt(now).
			Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("usersync: get tenant: %w", err)
	}

	upd := existing.Update().SetSyncedAt(now)
	if in.Slug != "" {
		upd = upd.SetSlug(in.Slug)
	}
	if in.Name != "" {
		upd = upd.SetName(in.Name)
	}
	upd = upd.SetStatus(in.Status).SetIsPlatform(in.IsPlatform)
	return upd.Save(ctx)
}

// EnsureTenantSlug guarantees a tenant shadow exists for (id, slug) WITHOUT clobbering a
// name/status already set by the auth.tenant.* event consumer. Used by the per-request JIT
// projection (middleware): on create it seeds name=slug; on an existing row it only refreshes
// the slug + synced_at. Cheap no-op when the slug already matches.
func (s *TenantSyncer) EnsureTenantSlug(ctx context.Context, id uuid.UUID, slug string) error {
	if id == uuid.Nil || slug == "" {
		return nil
	}
	now := time.Now().UTC()
	existing, err := s.orm.AuthTenant.Get(ctx, id)
	if ent.IsNotFound(err) {
		_, cerr := s.orm.AuthTenant.Create().
			SetID(id).SetSlug(slug).SetName(slug).SetStatus("active").SetSyncedAt(now).Save(ctx)
		return cerr
	}
	if err != nil {
		return err
	}
	if existing.Slug == slug {
		return nil
	}
	_, uerr := existing.Update().SetSlug(slug).SetSyncedAt(now).Save(ctx)
	return uerr
}

// OutletInput is the minimal data needed to upsert an outlet shadow.
type OutletInput struct {
	ID       uuid.UUID
	TenantID uuid.UUID
	Code     string
	Name     string
	UseCase  string
	IsHQ     bool
	Status   string
	Timezone string
}

// UpsertOutlet creates or updates the local AuthOutlet shadow.
func (s *TenantSyncer) UpsertOutlet(ctx context.Context, in OutletInput) (*ent.AuthOutlet, error) {
	if in.ID == uuid.Nil || in.TenantID == uuid.Nil {
		return nil, fmt.Errorf("usersync: outlet requires id and tenant_id")
	}
	if in.Status == "" {
		in.Status = "active"
	}
	now := time.Now().UTC()

	existing, err := s.orm.AuthOutlet.Get(ctx, in.ID)
	if ent.IsNotFound(err) {
		return s.orm.AuthOutlet.Create().
			SetID(in.ID).
			SetTenantID(in.TenantID).
			SetCode(in.Code).
			SetName(in.Name).
			SetUseCase(in.UseCase).
			SetIsHq(in.IsHQ).
			SetStatus(in.Status).
			SetTimezone(in.Timezone).
			SetSyncedAt(now).
			Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("usersync: get outlet: %w", err)
	}

	upd := existing.Update().
		SetTenantID(in.TenantID).
		SetStatus(in.Status).
		SetIsHq(in.IsHQ).
		SetSyncedAt(now)
	if in.Name != "" {
		upd = upd.SetName(in.Name)
	}
	if in.Code != "" {
		upd = upd.SetCode(in.Code)
	}
	if in.UseCase != "" {
		upd = upd.SetUseCase(in.UseCase)
	}
	if in.Timezone != "" {
		upd = upd.SetTimezone(in.Timezone)
	}
	return upd.Save(ctx)
}

// ArchiveOutlet marks an outlet archived (auth.outlet.archived).
func (s *TenantSyncer) ArchiveOutlet(ctx context.Context, id uuid.UUID) error {
	_, err := s.orm.AuthOutlet.Update().
		Where(authoutlet.ID(id)).
		SetStatus("archived").
		SetSyncedAt(time.Now().UTC()).
		Save(ctx)
	return err
}

// TenantBySlug returns the local tenant shadow for a slug, if present.
func (s *TenantSyncer) TenantBySlug(ctx context.Context, slug string) (*ent.AuthTenant, error) {
	return s.orm.AuthTenant.Query().Where(authtenant.Slug(slug)).Only(ctx)
}
