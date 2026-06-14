package main

import (
	"database/sql"
	"log"
)

// logSkip logs a per-row skip reason when --verbose is set (kept quiet otherwise so the
// reconcile report stays the primary signal).
func (m *Migrator) logSkip(table string, id int64, reason string) {
	if m.verbose {
		log.Printf("  skip %s id=%d: %s", table, id, reason)
	}
}

// orDefault returns the string value or a fallback for NULL/empty. Used where the Ent schema
// requires a non-empty field but the legacy column may be NULL.
func orDefault(v sql.NullString, def string) string {
	if v.Valid && v.String != "" {
		return v.String
	}
	return def
}

// columnsExist reports whether ALL named columns exist on a legacy table. Some Django tables
// drifted across migrations; this lets a per-table migration degrade cleanly (skip) when the
// expected column set is not present, instead of erroring on a bad SELECT.
func (m *Migrator) columnsExist(table string, cols ...string) bool {
	for _, c := range cols {
		var exists bool
		err := m.db.QueryRowContext(m.ctx,
			`SELECT EXISTS (SELECT 1 FROM information_schema.columns
			 WHERE table_schema='public' AND table_name=$1 AND column_name=$2)`, table, c).Scan(&exists)
		if err != nil || !exists {
			return false
		}
	}
	return true
}
