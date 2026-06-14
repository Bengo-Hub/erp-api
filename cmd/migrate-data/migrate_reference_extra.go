package main

import (
	"database/sql"

	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalcycle"
	"github.com/Bengo-Hub/erp-api/internal/ent/region"
	"github.com/Bengo-Hub/erp-api/internal/ent/withholdingtax"
)

// migrateRegions: regions -> Region. Reference data; Region.tenant_id is nillable (NULL =
// system-wide reference), so no tenant backfill is required — legacy regions are global and
// migrate as global reference rows. Self-referential parent_region remaps via deterministic
// UUID. Idempotent on the legacy-id UUID.
func (m *Migrator) migrateRegions() {
	m.guard("regions", "region", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, code, name, parent_region_id FROM regions`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var code, name sql.NullString
			var parent sql.NullInt64
			if err := rows.Scan(&id, &code, &name, &parent); err != nil {
				return st, err
			}
			st.read++
			newID := legacyIDToUUID("regions", id)
			exists, err := m.client.Region.Query().Where(region.IDEQ(newID)).Exist(m.ctx)
			if err != nil {
				return st, err
			}
			if exists {
				st.skipped++
				continue
			}
			if m.dryRun {
				st.written++
				continue
			}
			c := m.client.Region.Create().
				SetID(newID).
				SetName(orDefault(name, "Region"))
			if code.Valid && code.String != "" {
				c.SetCode(code.String)
			}
			if parent.Valid {
				c.SetParentRegionID(legacyIDToUUID("regions", parent.Int64))
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migrateAppraisalCycles: appraisals_appraisalcycle -> AppraisalCycle. The legacy table is
// tenant-less (Django global), so cycles are scoped to --default-tenant; without it every row
// is skipped (logged). created_by (CustomUser int FK) is deliberately NOT carried — user
// shadows re-form via SSO JIT (data-migration §4), so created_by is left NULL. The
// appraisals_appraisalcycle_locations M2M (cycle <-> core.Regions) has NO destination edge in
// the Ent AppraisalCycle schema and is therefore intentionally skipped (see migrateRun /
// reconcile note). status maps to the Ent enum, defaulting unknowns to "created".
func (m *Migrator) migrateAppraisalCycles() {
	m.guard("appraisals_appraisalcycle", "appraisal_cycle", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, name, description, start_date, end_date, due_date,
			status, created_at, updated_at FROM appraisals_appraisalcycle`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var name, description, status sql.NullString
			var startDate, endDate, dueDate, createdAt, updatedAt sql.NullTime
			if err := rows.Scan(&id, &name, &description, &startDate, &endDate, &dueDate,
				&status, &createdAt, &updatedAt); err != nil {
				return st, err
			}
			st.read++
			if m.defaultTenant == nil {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("appraisals_appraisalcycle", id)
			exists, err := m.client.AppraisalCycle.Query().Where(appraisalcycle.IDEQ(newID)).Exist(m.ctx)
			if err != nil {
				return st, err
			}
			if exists {
				st.skipped++
				continue
			}
			if m.dryRun {
				st.written++
				continue
			}
			c := m.client.AppraisalCycle.Create().
				SetID(newID).
				SetTenantID(*m.defaultTenant).
				SetName(orDefault(name, "Appraisal Cycle")).
				SetStatus(appraisalCycleStatus(strOrEmpty(status)))
			if startDate.Valid {
				c.SetStartDate(*nairobiTime(startDate))
			}
			if endDate.Valid {
				c.SetEndDate(*nairobiTime(endDate))
			}
			if dt := nairobiTime(dueDate); dt != nil {
				c.SetDueDate(*dt)
			}
			if description.Valid && description.String != "" {
				c.SetDescription(description.String)
			}
			if dt := nairobiTime(createdAt); dt != nil {
				c.SetCreatedAt(*dt)
			}
			if dt := nairobiTime(updatedAt); dt != nil {
				c.SetUpdatedAt(*dt)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// appraisalCycleStatus maps the legacy free-text status to the Ent enum, defaulting unknowns to
// the safe initial state "created".
func appraisalCycleStatus(s string) appraisalcycle.Status {
	switch s {
	case "activated":
		return appraisalcycle.StatusActivated
	case "closed":
		return appraisalcycle.StatusClosed
	case "reopened":
		return appraisalcycle.StatusReopened
	default:
		return appraisalcycle.StatusCreated
	}
}

// migrateTaxesTax: taxes_tax -> WithHoldingTax (best-effort). This legacy table is NOT present
// in the reference Django source tree (no `taxes` app there — the reference's only tax model is
// business.TaxRates -> "taxrates", a VAT/sales rate that belongs to inventory/pos, NOT to the
// ERP HR/payroll domain). To avoid a mis-map (rule: skip+log if unsure), this migration only
// proceeds when the prod table actually exposes a withholding-tax-shaped column set
// (a title/name + a rate/percentage). When the shape does not match, the row set is recorded as
// a reconciliation skip line rather than guessed into the wrong table. Scoped to
// --default-tenant (WithHoldingTax is tenant-NOT-NULL); skipped without it.
func (m *Migrator) migrateTaxesTax() {
	m.guard("taxes_tax", "withholding_tax", func() (tableStat, error) {
		var st tableStat
		// Resolve the actual column names present (prod schema unknown / unverified here).
		nameCol := firstPresentColumn(m, "taxes_tax", "title", "name", "tax_name")
		rateCol := firstPresentColumn(m, "taxes_tax", "rate", "percentage", "tax_rate")
		if nameCol == "" || rateCol == "" {
			// Shape does not match a withholding tax — DO NOT mis-map. Surface as a skip so the
			// reconcile report flags it for manual reconciliation (rule: skip+log if unsure).
			rows, err := m.query(`SELECT count(*) FROM taxes_tax`)
			if err == nil {
				defer func() { _ = rows.Close() }()
				if rows.Next() {
					_ = rows.Scan(&st.read)
				}
			}
			st.skipped = st.read
			m.logSkip("taxes_tax", 0, "column shape not withholding-tax-like; left for manual reconciliation")
			return st, nil
		}
		thresholdCol := firstPresentColumn(m, "taxes_tax", "threshold", "minimum", "min_amount")
		hasActive := m.columnsExist("taxes_tax", "is_active")
		hasEffFrom := m.columnsExist("taxes_tax", "effective_from")
		hasEffTo := m.columnsExist("taxes_tax", "effective_to")

		sel := "SELECT id, " + nameCol + " AS title, " + rateCol + " AS rate"
		if thresholdCol != "" {
			sel += ", " + thresholdCol + " AS threshold"
		} else {
			sel += ", NULL AS threshold"
		}
		if hasActive {
			sel += ", is_active"
		} else {
			sel += ", TRUE AS is_active"
		}
		if hasEffFrom {
			sel += ", effective_from"
		} else {
			sel += ", NULL::timestamptz AS effective_from"
		}
		if hasEffTo {
			sel += ", effective_to"
		} else {
			sel += ", NULL::timestamptz AS effective_to"
		}
		sel += " FROM taxes_tax"

		rows, err := m.query(sel)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var title, rate, threshold sql.NullString
			var isActive sql.NullBool
			var effFrom, effTo sql.NullTime
			if err := rows.Scan(&id, &title, &rate, &threshold, &isActive, &effFrom, &effTo); err != nil {
				return st, err
			}
			st.read++
			if m.defaultTenant == nil {
				st.skipped++ // WithHoldingTax is tenant-NOT-NULL; needs a tenant to land in
				continue
			}
			newID := legacyIDToUUID("taxes_tax", id)
			exists, err := m.client.WithHoldingTax.Query().Where(withholdingtax.IDEQ(newID)).Exist(m.ctx)
			if err != nil {
				return st, err
			}
			if exists {
				st.skipped++
				continue
			}
			if m.dryRun {
				st.written++
				continue
			}
			c := m.client.WithHoldingTax.Create().
				SetID(newID).
				SetTenantID(*m.defaultTenant).
				SetTitle(orDefault(title, "Withholding Tax")).
				SetRate(parseDecimal(rate)).
				SetThreshold(parseDecimal(threshold)).
				SetIsActive(boolOr(isActive, true))
			if dt := nairobiTime(effFrom); dt != nil {
				c.SetEffectiveFrom(*dt)
			}
			if dt := nairobiTime(effTo); dt != nil {
				c.SetEffectiveTo(*dt)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// firstPresentColumn returns the first of the candidate column names that exists on the table,
// or "" if none do. Used to tolerate prod-schema column-name drift on tables not present in the
// reference Django source.
func firstPresentColumn(m *Migrator, table string, candidates ...string) string {
	for _, c := range candidates {
		if m.columnsExist(table, c) {
			return c
		}
	}
	return ""
}
