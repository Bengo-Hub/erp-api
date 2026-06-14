package main

import (
	"database/sql"

	"github.com/Bengo-Hub/erp-api/internal/ent/companysettings"
	"github.com/Bengo-Hub/erp-api/internal/ent/department"
	"github.com/Bengo-Hub/erp-api/internal/ent/documentsequence"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobtitle"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
)

// migrateDepartments: core.departments -> Department. Reference data; tenant_id is nillable
// in the new schema (NULL = global), so no tenant backfill is required here. Idempotent on
// the deterministic legacy-id UUID.
func (m *Migrator) migrateDepartments() {
	m.guard("departments", "departments", func() (tableStat, error) {
		var st tableStat
		// Django FK column is "parent_departyment_id" (legacy typo preserved in the DB).
		rows, err := m.query(`SELECT id, title, code, parent_departyment_id FROM departments`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var title, code sql.NullString
			var parent sql.NullInt64
			if err := rows.Scan(&id, &title, &code, &parent); err != nil {
				return st, err
			}
			st.read++
			newID := legacyIDToUUID("departments", id)
			exists, err := m.client.Department.Query().Where(department.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.Department.Create().SetID(newID).SetTitle(orDefault(title, "Unnamed"))
			if code.Valid {
				c.SetCode(code.String)
			}
			if parent.Valid {
				c.SetParentDepartmentID(legacyIDToUUID("departments", parent.Int64))
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migrateJobTitles: jobtitles -> JobTitle. JobTitle is tenant-scoped (NOT NULL tenant_id) but
// the legacy table is global, so a --default-tenant is required to place them; without it
// every row is skipped (logged) rather than failing the run.
func (m *Migrator) migrateJobTitles() {
	m.guard("jobtitles", "job_titles", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, title FROM jobtitles`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var title sql.NullString
			if err := rows.Scan(&id, &title); err != nil {
				return st, err
			}
			st.read++
			if m.defaultTenant == nil {
				st.skipped++ // no tenant to scope global reference to
				continue
			}
			newID := legacyIDToUUID("jobtitles", id)
			exists, err := m.client.JobTitle.Query().Where(jobtitle.IDEQ(newID)).Exist(m.ctx)
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
			err = m.client.JobTitle.Create().
				SetID(newID).
				SetTenantID(*m.defaultTenant).
				SetTitle(orDefault(title, "Untitled")).
				Exec(m.ctx)
			if err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migrateCompanySettings: business_details -> CompanySettings (slim). One row per tenant
// (tenant_id is unique), so upsert-by-tenant. Branding/tax/pickup columns are deliberately
// dropped (owned by auth-api / payroll-tax / ordering — plan §0a). finacial_year_start_month
// (Django typo, month abbrev) -> financial_year_start_month int.
func (m *Migrator) migrateCompanySettings() {
	m.guard("business_details", "company_settings", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, tenant_id, name, finacial_year_start_month, currency FROM business_details`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var tenant, name, fyMonth, currency sql.NullString
			if err := rows.Scan(&id, &tenant, &name, &fyMonth, &currency); err != nil {
				return st, err
			}
			st.read++
			tid, ok := uuidFromNull(tenant)
			if !ok {
				st.skipped++ // un-tenanted business row cannot be a per-tenant settings row
				continue
			}
			exists, err := m.client.CompanySettings.Query().Where(companysettings.TenantID(tid)).Exist(m.ctx)
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
			c := m.client.CompanySettings.Create().
				SetTenantID(tid).
				SetFinancialYearStartMonth(monthAbbrevToInt(strOrEmpty(fyMonth)))
			if name.Valid {
				c.SetLegalName(name.String)
			}
			if currency.Valid && currency.String != "" {
				c.SetDefaultCurrency(currency.String)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migrateDocumentSequences: document_sequences -> DocumentSequence. current_sequence MUST be
// carried so numbering does not restart (data-migration §4). Upsert on (tenant_id, doc_type).
func (m *Migrator) migrateDocumentSequences() {
	m.guard("document_sequences", "document_sequences", func() (tableStat, error) {
		var st tableStat
		if !m.columnsExist("document_sequences", "tenant_id", "document_type", "current_sequence") {
			// Legacy schema variant lacks the expected columns — skip cleanly.
			return st, nil
		}
		rows, err := m.query(`SELECT id, tenant_id, document_type, prefix, current_sequence FROM document_sequences`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id, current int64
			var tenant, docType, prefix sql.NullString
			if err := rows.Scan(&id, &tenant, &docType, &prefix, &current); err != nil {
				return st, err
			}
			st.read++
			tid, ok := uuidFromNull(tenant)
			if !ok {
				st.skipped++
				continue
			}
			dt := orDefault(docType, "document")
			exists, err := m.client.DocumentSequence.Query().
				Where(documentsequence.TenantID(tid), documentsequence.DocTypeEQ(dt)).Exist(m.ctx)
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
			c := m.client.DocumentSequence.Create().
				SetTenantID(tid).SetDocType(dt).SetCurrentVal(current)
			if prefix.Valid {
				c.SetPrefix(prefix.String)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migrateLeaveCategories: leave_leavecategory -> LeaveCategory. Scoped to --default-tenant
// when present (legacy categories are global). Skipped when no tenant is available.
func (m *Migrator) migrateLeaveCategories() {
	m.guard("leave_leavecategory", "leave_categories", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, name, description, is_active, default_annual_days FROM leave_leavecategory`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var name, desc, days sql.NullString
			var active sql.NullBool
			if err := rows.Scan(&id, &name, &desc, &active, &days); err != nil {
				return st, err
			}
			st.read++
			if m.defaultTenant == nil {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("leave_leavecategory", id)
			exists, err := m.client.LeaveCategory.Query().Where(leavecategory.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.LeaveCategory.Create().
				SetID(newID).
				SetTenantID(*m.defaultTenant).
				SetName(orDefault(name, "Leave")).
				SetIsActive(boolOr(active, true)).
				SetDefaultAnnualDays(parseDecimal(days))
			if desc.Valid {
				c.SetDescription(desc.String)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}
