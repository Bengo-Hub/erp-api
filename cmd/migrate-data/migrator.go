package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"sort"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// Migrator carries the shared state for a single migration run: the raw SQL handle used to
// read the legacy Django tables, the Ent client used to write the new schema, the run flags,
// and the per-table reconciliation counters.
//
// Both legacy and new tables live in the SAME database (plan §0c) — the migrator just reads
// old table names and writes new ones via Ent. There is therefore one connection.
type Migrator struct {
	db     *sql.DB
	client *ent.Client
	ctx    context.Context

	dryRun  bool
	only    string // if set, only this legacy table is migrated
	verbose bool

	// tenantByOrg maps a legacy business_details (organisation) integer PK to its auth-api
	// tenant_id UUID. Built once up-front; used to backfill tenant_id on every HR row.
	tenantByOrg map[int64]uuid.UUID
	// defaultTenant is used for HR rows whose organisation resolves to no tenant, ONLY when
	// --default-tenant is supplied; otherwise such rows hard-fail (no cross-tenant leak).
	defaultTenant *uuid.UUID

	stats []tableStat
}

// tableStat is one line of the end-of-run reconciliation report.
type tableStat struct {
	legacy  string // source Django table
	dest    string // destination Ent table (display)
	read    int    // rows read from source
	written int    // rows written/upserted to dest
	skipped int    // rows skipped (already present / unresolved)
	missing bool   // source table absent in this DB (degraded clean)
}

// shouldRun reports whether the given legacy table is in scope for this run, honoring --only.
func (m *Migrator) shouldRun(legacyTable string) bool {
	return m.only == "" || m.only == legacyTable
}

// tableExists checks for a legacy source table in the public schema. Missing tables are
// skipped with a logged warning so --dry-run runs clean on a local DB that lacks the legacy
// Django schema (build/verify-without-prod requirement).
func (m *Migrator) tableExists(table string) bool {
	var exists bool
	err := m.db.QueryRowContext(m.ctx,
		`SELECT EXISTS (SELECT 1 FROM information_schema.tables
		 WHERE table_schema='public' AND table_name=$1)`, table).Scan(&exists)
	if err != nil {
		log.Printf("WARN: existence check for %q failed: %v", table, err)
		return false
	}
	return exists
}

// query runs a read against a legacy table, returning rows the caller scans.
func (m *Migrator) query(q string, args ...any) (*sql.Rows, error) {
	return m.db.QueryContext(m.ctx, q, args...)
}

// record appends a reconciliation line.
func (m *Migrator) record(s tableStat) {
	m.stats = append(m.stats, s)
}

// guard wraps a per-table migration: it honors --only, checks the source table exists
// (degrading cleanly when absent), and records a skipped/missing stat as appropriate.
// The fn returns a tableStat with read/written/skipped populated.
func (m *Migrator) guard(legacy, dest string, fn func() (tableStat, error)) {
	if !m.shouldRun(legacy) {
		return
	}
	if !m.tableExists(legacy) {
		log.Printf("SKIP %-32s source table absent (degraded clean)", legacy)
		m.record(tableStat{legacy: legacy, dest: dest, missing: true})
		return
	}
	st, err := fn()
	st.legacy, st.dest = legacy, dest
	if err != nil {
		log.Printf("ERROR migrating %s -> %s: %v", legacy, dest, err)
	}
	mode := "wrote"
	if m.dryRun {
		mode = "would-write"
	}
	log.Printf("DONE %-32s read=%d %s=%d skipped=%d", legacy, st.read, mode, st.written, st.skipped)
	m.record(st)
}

// resolveTenant returns the tenant_id for a legacy organisation FK, applying the default
// tenant fallback when configured. The bool is false when the row cannot be tenant-resolved
// and no default is set — the caller MUST skip/fail such rows (no silent cross-tenant leak).
func (m *Migrator) resolveTenant(orgID sql.NullInt64) (uuid.UUID, bool) {
	if orgID.Valid {
		if t, ok := m.tenantByOrg[orgID.Int64]; ok {
			return t, true
		}
	}
	if m.defaultTenant != nil {
		return *m.defaultTenant, true
	}
	return uuid.Nil, false
}

// loadTenantMap builds organisation-PK -> tenant_id from business_details. HR rows derive
// their tenant via Employee.organisation -> business_details.tenant_id (data-migration §1).
func (m *Migrator) loadTenantMap() error {
	m.tenantByOrg = map[int64]uuid.UUID{}
	if !m.tableExists("business_details") {
		log.Printf("WARN: business_details absent — tenant backfill relies on --default-tenant only")
		return nil
	}
	rows, err := m.query(`SELECT id, tenant_id FROM business_details WHERE tenant_id IS NOT NULL`)
	if err != nil {
		return err
	}
	defer func() { _ = rows.Close() }()
	for rows.Next() {
		var id int64
		var tid sql.NullString
		if err := rows.Scan(&id, &tid); err != nil {
			return err
		}
		if t, ok := uuidFromNull(tid); ok {
			m.tenantByOrg[id] = t
		}
	}
	log.Printf("tenant map: %d organisations -> tenant_id", len(m.tenantByOrg))
	return rows.Err()
}

// reconcile prints the end-of-run source-vs-written report and a parity summary.
func (m *Migrator) reconcile() {
	sort.SliceStable(m.stats, func(i, j int) bool { return m.stats[i].legacy < m.stats[j].legacy })
	fmt.Println()
	fmt.Println("================ RECONCILIATION REPORT ================")
	fmt.Printf("%-32s %-26s %8s %8s %8s\n", "SOURCE (Django)", "DEST (Ent)", "READ", "WRITTEN", "SKIPPED")
	var totRead, totWritten, totSkipped, parityWarn int
	for _, s := range m.stats {
		if s.missing {
			fmt.Printf("%-32s %-26s %8s %8s %8s   (source table absent)\n", s.legacy, s.dest, "-", "-", "-")
			continue
		}
		fmt.Printf("%-32s %-26s %8d %8d %8d\n", s.legacy, s.dest, s.read, s.written, s.skipped)
		totRead += s.read
		totWritten += s.written
		totSkipped += s.skipped
		if s.written+s.skipped != s.read {
			parityWarn++
		}
	}
	fmt.Println("-------------------------------------------------------")
	fmt.Printf("%-32s %-26s %8d %8d %8d\n", "TOTAL", "", totRead, totWritten, totSkipped)
	mode := "WRITE"
	if m.dryRun {
		mode = "DRY-RUN (no writes performed)"
	}
	fmt.Printf("mode: %s\n", mode)
	if parityWarn > 0 {
		fmt.Printf("PARITY WARNING: %d table(s) where written+skipped != read — investigate before cutover.\n", parityWarn)
	} else {
		fmt.Println("parity: OK (written+skipped == read for every migrated table)")
	}
	fmt.Println("=======================================================")
}
