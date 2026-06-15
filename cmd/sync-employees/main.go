// Command sync-employees is a one-time backfill that projects auth-api users into erp
// Employees (keyed on the auth user id) for tenants whose employee roster is still empty or
// full of blank placeholder rows. It mirrors the cmd/seed bootstrap (config.Load + Ent over
// the runtime DSN) but additionally calls the auth-api S2S endpoint
// GET /api/v1/s2s/{tenant}/users (X-API-Key: INTERNAL_SERVICE_KEY) to enumerate members.
//
// For each tenant it: lists active members, calls employees.UpsertFromAuthUser (skipping the
// platform owner/superuser via consumers.IsPlatformAdmin), then SOFT-DELETES leftover keyless
// junk employees (user_id IS NULL AND first_name='' AND last_name='' AND email='').
//
// Usage:
//
//	# one tenant (slug or UUID)
//	INTERNAL_SERVICE_KEY=... AUTH_SERVICE_URL=https://sso... \
//	  go run ./cmd/sync-employees <tenant-slug-or-id>
//
//	# every tenant present in the local auth_tenant shadow table
//	INTERNAL_SERVICE_KEY=... AUTH_SERVICE_URL=https://sso... \
//	  go run ./cmd/sync-employees --all
//
// It DOES NOT hardcode any tenant id or user data, and is intended to be run manually after
// review — NOT against prod automatically.
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/joho/godotenv"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/authtenant"
	"github.com/Bengo-Hub/erp-api/internal/modules/consumers"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
)

// s2sUser mirrors the auth-api GET /api/v1/s2s/{tenant}/users response item.
type s2sUser struct {
	ID       string   `json:"id"`
	Email    string   `json:"email"`
	Name     string   `json:"name"`
	Roles    []string `json:"roles"`
	OutletID *string  `json:"outlet_id,omitempty"`
}

func main() {
	_ = godotenv.Load()

	all := flag.Bool("all", false, "backfill every tenant in the local auth_tenant shadow table")
	flag.Parse()
	arg := strings.TrimSpace(flag.Arg(0))

	if !*all && arg == "" {
		log.Fatalf("usage: sync-employees <tenant-slug-or-id> | --all")
	}

	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("load config: %v", err)
	}
	if strings.TrimSpace(cfg.Auth.APIKey) == "" {
		log.Fatalf("INTERNAL_SERVICE_KEY is required for the auth-api S2S call")
	}
	authBase := strings.TrimRight(cfg.Auth.ServiceURL, "/")
	if authBase == "" {
		log.Fatalf("AUTH_SERVICE_URL is required")
	}

	// Runtime DSN (pgbouncer) — this is a read+write backfill against live tables.
	sqlDB, err := sql.Open("pgx", cfg.Postgres.DSN())
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	defer func() { _ = sqlDB.Close() }()

	client := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, sqlDB)))
	defer func() { _ = client.Close() }()

	ctx := context.Background()
	svc := employees.NewService(client)
	httpClient := &http.Client{Timeout: 20 * time.Second}

	// Resolve the target tenants. For --all we read the local auth_tenant shadow; for a single
	// arg we resolve its UUID (passing the raw arg to the S2S call, which accepts slug or id).
	type target struct {
		tenantID uuid.UUID
		ref      string // slug or id passed to the S2S endpoint
	}
	var targets []target

	if *all {
		tenants, err := client.AuthTenant.Query().All(ctx)
		if err != nil {
			log.Fatalf("list local tenants: %v", err)
		}
		for _, t := range tenants {
			ref := t.Slug
			if ref == "" {
				ref = t.ID.String()
			}
			targets = append(targets, target{tenantID: t.ID, ref: ref})
		}
		if len(targets) == 0 {
			log.Fatalf("--all: no tenants found in the local auth_tenant shadow")
		}
	} else {
		tid, err := resolveTenantID(ctx, client, arg)
		if err != nil {
			log.Fatalf("resolve tenant %q: %v", arg, err)
		}
		targets = append(targets, target{tenantID: tid, ref: arg})
	}

	var totalCreatedUpdated, totalSkipped, totalDeleted int
	for _, t := range targets {
		users, err := fetchUsers(ctx, httpClient, authBase, cfg.Auth.APIKey, t.ref)
		if err != nil {
			log.Printf("tenant %s: list users failed: %v (skipping)", t.ref, err)
			continue
		}

		created, skipped := 0, 0
		for _, u := range users {
			authUserID, perr := uuid.Parse(strings.TrimSpace(u.ID))
			if perr != nil || authUserID == uuid.Nil {
				log.Printf("tenant %s: skip user with invalid id %q", t.ref, u.ID)
				continue
			}
			if consumers.IsPlatformAdmin(u.Email, u.Roles) {
				skipped++
				continue
			}
			var outletID *uuid.UUID
			if u.OutletID != nil {
				if oid, oerr := uuid.Parse(strings.TrimSpace(*u.OutletID)); oerr == nil && oid != uuid.Nil {
					outletID = &oid
				}
			}
			if _, uerr := svc.UpsertFromAuthUser(ctx, t.tenantID, authUserID, u.Email, u.Name, outletID, false); uerr != nil {
				log.Printf("tenant %s: upsert user %s failed: %v", t.ref, authUserID, uerr)
				continue
			}
			created++
		}

		deleted, derr := svc.SoftDeleteBlankPlaceholders(ctx, t.tenantID)
		if derr != nil {
			log.Printf("tenant %s: soft-delete blank placeholders failed: %v", t.ref, derr)
		}

		log.Printf("tenant %s (%s): {created_or_updated: %d, skipped_platform_admin: %d, soft_deleted: %d}",
			t.ref, t.tenantID, created, skipped, deleted)
		totalCreatedUpdated += created
		totalSkipped += skipped
		totalDeleted += deleted
	}

	log.Printf("sync-employees complete: {tenants: %d, created_or_updated: %d, skipped_platform_admin: %d, soft_deleted: %d}",
		len(targets), totalCreatedUpdated, totalSkipped, totalDeleted)
}

// resolveTenantID resolves a slug/UUID arg to the tenant UUID using the local auth_tenant
// shadow (slug) or by parsing the arg directly (UUID).
func resolveTenantID(ctx context.Context, client *ent.Client, arg string) (uuid.UUID, error) {
	if tid, err := uuid.Parse(arg); err == nil {
		return tid, nil
	}
	t, err := client.AuthTenant.Query().Where(authtenant.Slug(arg)).Only(ctx)
	if err != nil {
		return uuid.Nil, fmt.Errorf("tenant slug not found in local shadow (run the tenant-sync first): %w", err)
	}
	return t.ID, nil
}

// fetchUsers calls the auth-api S2S endpoint to list a tenant's active members.
func fetchUsers(ctx context.Context, hc *http.Client, base, apiKey, tenantRef string) ([]s2sUser, error) {
	url := fmt.Sprintf("%s/api/v1/s2s/%s/users", base, tenantRef)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-API-Key", apiKey)
	resp, err := hc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("auth s2s users: status %d", resp.StatusCode)
	}
	var users []s2sUser
	if err := json.NewDecoder(resp.Body).Decode(&users); err != nil {
		return nil, fmt.Errorf("auth s2s users: decode: %w", err)
	}
	return users, nil
}
