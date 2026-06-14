package main

import (
	"database/sql"

	"github.com/Bengo-Hub/erp-api/internal/ent/payrollcomponent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformulaitem"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollrelief"
)

// migratePayrollReliefs: payroll_settings_relief -> PayrollRelief. The legacy table is global
// (tenant-less Django reference), so it is scoped to --default-tenant when present; without
// it every row is skipped (logged) rather than failing the run — same convention as jobtitles
// / leave_leavecategory. Idempotent on the deterministic legacy-id UUID. Reliefs are migrated
// BEFORE PayrollComponent because a component may FK applicable_relief.
func (m *Migrator) migratePayrollReliefs() {
	m.guard("payroll_settings_relief", "payroll_relief", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, type, title, actual_amount, fixed_limit,
			percentage, percent_of, is_active FROM payroll_settings_relief`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var rtype, title, percentOf sql.NullString
			var fixedLimit, percentage sql.NullString
			var actualAmount, isActive sql.NullBool
			if err := rows.Scan(&id, &rtype, &title, &actualAmount, &fixedLimit,
				&percentage, &percentOf, &isActive); err != nil {
				return st, err
			}
			st.read++
			if m.defaultTenant == nil {
				st.skipped++ // no tenant to scope a global reference row to
				continue
			}
			newID := legacyIDToUUID("payroll_settings_relief", id)
			exists, err := m.client.PayrollRelief.Query().Where(payrollrelief.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.PayrollRelief.Create().
				SetID(newID).
				SetTenantID(*m.defaultTenant).
				SetType(orDefault(rtype, "Personal")).
				SetTitle(orDefault(title, "Relief")).
				SetActualAmount(boolOr(actualAmount, true)).
				SetFixedLimit(parseDecimal(fixedLimit)).
				SetPercentage(parseDecimal(percentage)).
				SetIsActive(boolOr(isActive, false))
			if p := strPtr(percentOf); p != nil {
				c.SetPercentOf(*p)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migratePayrollComponents: payroll_settings_payrollcomponents -> PayrollComponent. Global
// legacy reference scoped to --default-tenant. FK remaps: applicable_relief -> migrated
// PayrollRelief UUID, applicable_tax_formula -> migrated BenefitTax UUID (legacy
// payroll_settings_benefittaxes). deduction_phase/priority carried for engine ordering.
func (m *Migrator) migratePayrollComponents() {
	m.guard("payroll_settings_payrollcomponents", "payroll_component", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, wb_code, acc_code, title, category, description, mode,
			non_cash, deduct_after_taxing, applicable_relief_id, applicable_tax_formula_id,
			checkoff, constant, statutory, is_active, taxable_status,
			deduction_phase, deduction_priority
			FROM payroll_settings_payrollcomponents`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var wbCode, accCode, title, category, description, mode, taxableStatus, phase sql.NullString
			var nonCash, deductAfter, checkoff, constant, statutory, isActive sql.NullBool
			var reliefID, taxFormulaID sql.NullInt64
			var priority sql.NullInt64
			if err := rows.Scan(&id, &wbCode, &accCode, &title, &category, &description, &mode,
				&nonCash, &deductAfter, &reliefID, &taxFormulaID,
				&checkoff, &constant, &statutory, &isActive, &taxableStatus,
				&phase, &priority); err != nil {
				return st, err
			}
			st.read++
			if m.defaultTenant == nil {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("payroll_settings_payrollcomponents", id)
			exists, err := m.client.PayrollComponent.Query().Where(payrollcomponent.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.PayrollComponent.Create().
				SetID(newID).
				SetTenantID(*m.defaultTenant).
				SetTitle(orDefault(title, "Component")).
				SetNonCash(boolOr(nonCash, false)).
				SetDeductAfterTaxing(boolOr(deductAfter, false)).
				SetCheckoff(boolOr(checkoff, true)).
				SetConstant(boolOr(constant, true)).
				SetStatutory(boolOr(statutory, false)).
				SetIsActive(boolOr(isActive, true)).
				SetDeductionPhase(orDefault(phase, "before_tax"))
			if category.Valid && category.String != "" {
				c.SetCategory(category.String)
			}
			if mode.Valid && mode.String != "" {
				c.SetMode(mode.String)
			}
			if taxableStatus.Valid && taxableStatus.String != "" {
				c.SetTaxableStatus(taxableStatus.String)
			}
			if p := strPtr(wbCode); p != nil {
				c.SetWbCode(*p)
			}
			if p := strPtr(accCode); p != nil {
				c.SetAccCode(*p)
			}
			if p := strPtr(description); p != nil {
				c.SetDescription(*p)
			}
			if priority.Valid && priority.Int64 > 0 {
				c.SetDeductionPriority(int(priority.Int64))
			}
			if reliefID.Valid {
				c.SetApplicableReliefID(legacyIDToUUID("payroll_settings_relief", reliefID.Int64))
			}
			if taxFormulaID.Valid {
				c.SetApplicableTaxFormulaID(legacyIDToUUID("payroll_settings_benefittaxes", taxFormulaID.Int64))
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migratePayrollFormulas: payroll_settings_formulas -> PayrollFormula. Global legacy reference
// scoped to --default-tenant. The legacy "deduction" FK (-> payrollcomponents) remaps to the
// migrated PayrollComponent UUID via component_id. effective dates -> Africa/Nairobi. Money
// columns are exact decimals (never float). deduction_order JSON is intentionally NOT carried
// in this pass (engine re-derives phasing from components — data-migration §4).
func (m *Migrator) migratePayrollFormulas() {
	m.guard("payroll_settings_formulas", "payroll_formula", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, type, category, title, unit, deduction_id,
			effective_from, effective_to, upper_limit, upper_limit_amount, upper_limit_percentage,
			personal_relief, relief_carry_forward, min_taxable_income, progressive,
			version, regulatory_source, notes, is_current
			FROM payroll_settings_formulas`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var ftype, category, title, unit, version, regSource, notes sql.NullString
			var deductionID sql.NullInt64
			var effFrom, effTo sql.NullTime
			var upperLimit, upperLimitAmt, upperLimitPct, personalRelief, minTaxable sql.NullString
			var carryForward, progressive, isCurrent sql.NullBool
			if err := rows.Scan(&id, &ftype, &category, &title, &unit, &deductionID,
				&effFrom, &effTo, &upperLimit, &upperLimitAmt, &upperLimitPct,
				&personalRelief, &carryForward, &minTaxable, &progressive,
				&version, &regSource, &notes, &isCurrent); err != nil {
				return st, err
			}
			st.read++
			if m.defaultTenant == nil {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("payroll_settings_formulas", id)
			exists, err := m.client.PayrollFormula.Query().Where(payrollformula.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.PayrollFormula.Create().
				SetID(newID).
				SetTenantID(*m.defaultTenant).
				SetType(orDefault(ftype, "income")).
				SetTitle(orDefault(title, "Formula")).
				SetUnit(orDefault(unit, "KES")).
				SetUpperLimit(parseDecimal(upperLimit)).
				SetUpperLimitAmount(parseDecimal(upperLimitAmt)).
				SetUpperLimitPercentage(parseDecimal(upperLimitPct)).
				SetPersonalRelief(parseDecimal(personalRelief)).
				SetReliefCarryForward(boolOr(carryForward, false)).
				SetMinTaxableIncome(parseDecimal(minTaxable)).
				SetProgressive(boolOr(progressive, false)).
				SetVersion(orDefault(version, "1.0")).
				SetIsCurrent(boolOr(isCurrent, false))
			if category.Valid && category.String != "" {
				c.SetCategory(category.String)
			}
			if p := strPtr(regSource); p != nil {
				c.SetRegulatorySource(*p)
			}
			if p := strPtr(notes); p != nil {
				c.SetNotes(*p)
			}
			if dt := nairobiTime(effFrom); dt != nil {
				c.SetEffectiveFrom(*dt)
			}
			if dt := nairobiTime(effTo); dt != nil {
				c.SetEffectiveTo(*dt)
			}
			if deductionID.Valid {
				c.SetComponentID(legacyIDToUUID("payroll_settings_payrollcomponents", deductionID.Int64))
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migratePayrollFormulaItems: payroll_settings_formulaitems -> PayrollFormulaItem. Each row is
// a tax bracket/band of a formula. formula FK remaps to the migrated PayrollFormula UUID;
// tenant inherited from --default-tenant (same scope the parent formula migrated under). Money
// columns are exact decimals.
func (m *Migrator) migratePayrollFormulaItems() {
	m.guard("payroll_settings_formulaitems", "payroll_formula_item", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, formula_id, amount_from, amount_to,
			deduct_amount, deduct_percentage FROM payroll_settings_formulaitems`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id, formulaID int64
			var amountFrom, amountTo, deductAmount, deductPct sql.NullString
			if err := rows.Scan(&id, &formulaID, &amountFrom, &amountTo,
				&deductAmount, &deductPct); err != nil {
				return st, err
			}
			st.read++
			if m.defaultTenant == nil {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("payroll_settings_formulaitems", id)
			exists, err := m.client.PayrollFormulaItem.Query().Where(payrollformulaitem.IDEQ(newID)).Exist(m.ctx)
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
			err = m.client.PayrollFormulaItem.Create().
				SetID(newID).
				SetTenantID(*m.defaultTenant).
				SetFormulaID(legacyIDToUUID("payroll_settings_formulas", formulaID)).
				SetAmountFrom(parseDecimal(amountFrom)).
				SetAmountTo(parseDecimal(amountTo)).
				SetDeductAmount(parseDecimal(deductAmount)).
				SetDeductPercentage(parseDecimal(deductPct)).
				Exec(m.ctx)
			if err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}
