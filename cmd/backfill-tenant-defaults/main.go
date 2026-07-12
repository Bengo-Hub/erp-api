// Command backfill-tenant-defaults ensures a SINGLE tenant has the full set of per-tenant
// payroll/HR bootstrap data that cmd/seed-defaults normally provisions for every tenant, plus
// the tenant-level KRA reliefs and a general_hr_settings row (statutory toggles ON) — for
// tenants that were created before those seeders ran, or whose bootstrap was otherwise skipped.
//
// Idempotent: reuses defaults.Service.EnsureAll + defaults.EnsureReliefsWithClient, both of
// which no-op on rows that already exist. The general_hr_settings row is only created if one
// doesn't already exist for the tenant (existing rows are left untouched).
//
// Usage:
//
//	POSTGRES_MIGRATE_URL=postgres://... go run ./cmd/backfill-tenant-defaults <tenant-slug-or-id>
package main

import (
	"context"
	"database/sql"
	"flag"
	"log"
	"strings"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/joho/godotenv"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/authtenant"
	"github.com/Bengo-Hub/erp-api/internal/ent/generalhrsettings"
	"github.com/Bengo-Hub/erp-api/internal/modules/defaults"
)

func main() {
	_ = godotenv.Load()
	flag.Parse()
	arg := strings.TrimSpace(flag.Arg(0))
	if arg == "" {
		log.Fatalf("usage: backfill-tenant-defaults <tenant-slug-or-id>")
	}

	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("load config: %v", err)
	}
	dsn := cfg.Postgres.MigrateDSN()
	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	defer func() { _ = sqlDB.Close() }()
	client := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, sqlDB)))
	defer func() { _ = client.Close() }()

	ctx := context.Background()

	tenantID, err := resolveTenantID(ctx, client, arg)
	if err != nil {
		log.Fatalf("resolve tenant %q: %v", arg, err)
	}

	if err := defaults.NewService(client).EnsureAll(ctx, tenantID); err != nil {
		log.Fatalf("EnsureAll: %v", err)
	}
	log.Printf("  ensured job groups / leave categories / appraisal template / goal library / document sequences")

	if err := defaults.EnsureReliefsWithClient(ctx, client, tenantID); err != nil {
		log.Fatalf("EnsureReliefs: %v", err)
	}
	log.Printf("  ensured tenant KRA reliefs")

	if err := ensureGeneralHRSettings(ctx, client, tenantID); err != nil {
		log.Fatalf("ensureGeneralHRSettings: %v", err)
	}

	log.Printf("backfill-tenant-defaults: done for tenant %s", tenantID)
}

func resolveTenantID(ctx context.Context, client *ent.Client, arg string) (uuid.UUID, error) {
	if tid, err := uuid.Parse(arg); err == nil {
		return tid, nil
	}
	t, err := client.AuthTenant.Query().Where(authtenant.Slug(arg)).Only(ctx)
	if err != nil {
		return uuid.Nil, err
	}
	return t.ID, nil
}

// ensureGeneralHRSettings creates a default statutory-toggle row (all ON) for the tenant if one
// doesn't already exist. Mirrors the shape of a properly onboarded tenant's row.
func ensureGeneralHRSettings(ctx context.Context, client *ent.Client, tenantID uuid.UUID) error {
	exists, err := client.GeneralHRSettings.Query().
		Where(generalhrsettings.TenantID(tenantID)).Exist(ctx)
	if err != nil {
		return err
	}
	if exists {
		log.Printf("  skip general_hr_settings (already configured)")
		return nil
	}
	_, err = client.GeneralHRSettings.Create().
		SetTenantID(tenantID).
		SetOvertimeNormalDays(decimal.Zero).
		SetOvertimeNonWorkingDays(decimal.Zero).
		SetOvertimeHolidays(decimal.Zero).
		SetPartialMonths("prorate_calendar").
		SetRoundOffCurrency("KES").
		SetRoundOffAmount(decimal.Zero).
		SetAllowBackwardsPayroll(false).
		SetPayeEnabled(true).
		SetNssfEnabled(true).
		SetShifEnabled(true).
		SetHousingLevyEnabled(true).
		SetNitaEnabled(true).
		Save(ctx)
	if err != nil {
		return err
	}
	log.Printf("  seeded general_hr_settings (statutory toggles ON)")
	return nil
}
