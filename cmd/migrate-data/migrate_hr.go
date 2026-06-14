package main

import (
	"database/sql"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/contract"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebankaccount"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
)

// migrateEmployees: employee -> Employee. The HR FK hub. tenant_id is backfilled from
// organisation -> business_details.tenant_id; rows that cannot be tenant-resolved are
// skipped (or assigned --default-tenant) — NEVER written with a NULL/guessed tenant (no
// cross-tenant leak, plan risk table). The row's UUID is derived deterministically from the
// legacy PK so child tables can remap FKs without a lookup table, and re-runs are idempotent.
//
// user_id (auth CustomUser, integer PK) is deliberately NOT carried — SSO JIT recreates the
// user shadow from the JWT sub (data-migration §4); the link re-forms on first login.
func (m *Migrator) migrateEmployees() {
	m.guard("employee", "employee", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, organisation_id, outlet_id, gender, date_of_birth,
			residential_status, national_id, pin_no, shif_or_nhif_number, nssf_no,
			deleted, terminated FROM employee`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id int64
			var org sql.NullInt64
			var outlet, gender, dobNull, resStatus, natID, pin, shif, nssf sql.NullString
			var deleted, terminated sql.NullBool
			var dob sql.NullTime
			// date_of_birth scanned as time; residential_status etc as strings.
			if err := rows.Scan(&id, &org, &outlet, &gender, &dob, &resStatus,
				&natID, &pin, &shif, &nssf, &deleted, &terminated); err != nil {
				return st, err
			}
			_ = dobNull
			st.read++
			tid, ok := m.resolveTenant(org)
			if !ok {
				m.logSkip("employee", id, "unresolved tenant (NULL organisation, no --default-tenant)")
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("employee", id)
			exists, err := m.client.Employee.Query().Where(employee.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.Employee.Create().
				SetID(newID).
				SetTenantID(tid).
				SetGender(strOrEmpty(gender)).
				SetResidentialStatus(strOrEmpty(resStatus)).
				SetNationalID(strOrEmpty(natID)).
				SetPinNo(strOrEmpty(pin)).
				SetNssfNo(strOrEmpty(nssf)).
				SetDeleted(boolOr(deleted, false)).
				SetTerminated(boolOr(terminated, false))
			if oid, ok := uuidFromNull(outlet); ok {
				c.SetOutletID(oid)
			}
			if dt := nairobiTime(dob); dt != nil {
				c.SetDateOfBirth(*dt)
			}
			if p := strPtr(shif); p != nil {
				c.SetShifOrNhifNumber(*p)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// employeeTenant resolves the tenant_id for an employee legacy PK by re-deriving the employee
// UUID and reading its persisted tenant. Child HR tables call this so they inherit the same
// tenant the employee was migrated under (and so they skip rows whose parent was skipped).
func (m *Migrator) employeeTenant(empLegacyID int64) (uuid.UUID, bool) {
	e, err := m.client.Employee.Query().
		Where(employee.IDEQ(legacyIDToUUID("employee", empLegacyID))).
		Only(m.ctx)
	if err != nil {
		return uuid.Nil, false
	}
	return e.TenantID, true
}

// migrateBankAccounts: employee_bank_accounts -> EmployeeBankAccount. Bank masters were
// decomposed (banks = payment-rail reference); bank name/branch are carried as plain fields
// (plan §0a). Idempotent on the deterministic legacy-id UUID; tenant inherited from employee.
func (m *Migrator) migrateBankAccounts() {
	m.guard("employee_bank_accounts", "employee_bank_accounts", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, employee_id, account_name, account_number,
			account_type, is_primary FROM employee_bank_accounts`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id, empID int64
			var name, number, acctType sql.NullString
			var primary sql.NullBool
			if err := rows.Scan(&id, &empID, &name, &number, &acctType, &primary); err != nil {
				return st, err
			}
			st.read++
			tid, ok := m.employeeTenant(empID)
			if !ok {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("employee_bank_accounts", id)
			exists, err := m.client.EmployeeBankAccount.Query().Where(employeebankaccount.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.EmployeeBankAccount.Create().
				SetID(newID).
				SetTenantID(tid).
				SetEmployeeID(legacyIDToUUID("employee", empID)).
				SetAccountName(strOrEmpty(name)).
				SetAccountNumber(strOrEmpty(number)).
				SetIsPrimary(boolOr(primary, false))
			if acctType.Valid && acctType.String != "" {
				c.SetAccountType(acctType.String)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migrateHRDetails: employee_hr_details -> HRDetails (org placement). FK remaps: job_title,
// department, reports_to (manager) via deterministic UUIDs. Tenant inherited from employee.
func (m *Migrator) migrateHRDetails() {
	m.guard("employee_hr_details", "hr_details", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, employee_id, job_title_id, department_id,
			head_of_id, reports_to_id, date_of_employment FROM employee_hr_details`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id, empID int64
			var jobTitle, dept, headOf, reportsTo sql.NullInt64
			var doe sql.NullTime
			if err := rows.Scan(&id, &empID, &jobTitle, &dept, &headOf, &reportsTo, &doe); err != nil {
				return st, err
			}
			st.read++
			tid, ok := m.employeeTenant(empID)
			if !ok {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("employee_hr_details", id)
			exists, err := m.client.HRDetails.Query().Where(hrdetails.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.HRDetails.Create().
				SetID(newID).SetTenantID(tid).
				SetEmployeeID(legacyIDToUUID("employee", empID))
			if jobTitle.Valid {
				c.SetJobTitleID(legacyIDToUUID("jobtitles", jobTitle.Int64))
			}
			if dept.Valid {
				c.SetDepartmentID(legacyIDToUUID("departments", dept.Int64))
			}
			if headOf.Valid {
				c.SetHeadOfDepartmentID(legacyIDToUUID("departments", headOf.Int64))
			}
			if reportsTo.Valid {
				c.SetReportsToID(legacyIDToUUID("employee", reportsTo.Int64))
			}
			if dt := nairobiTime(doe); dt != nil {
				c.SetDateJoined(*dt)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migrateSalaryDetails: employee_salary_details -> SalaryDetails. Derived rates
// (hourly/daily) are NOT trusted from the stale stored values — left at default 0 and
// recomputed by the Go service on first write (data-migration §4). monthly_salary is decimal.
func (m *Migrator) migrateSalaryDetails() {
	m.guard("employee_salary_details", "salary_details", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, employee_id, monthly_salary, payment_currency,
			income_tax, bank_account_id FROM employee_salary_details`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id, empID int64
			var salary, currency, incomeTax sql.NullString
			var bankAcct sql.NullInt64
			if err := rows.Scan(&id, &empID, &salary, &currency, &incomeTax, &bankAcct); err != nil {
				return st, err
			}
			st.read++
			tid, ok := m.employeeTenant(empID)
			if !ok {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("employee_salary_details", id)
			exists, err := m.client.SalaryDetails.Query().Where(salarydetails.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.SalaryDetails.Create().
				SetID(newID).SetTenantID(tid).
				SetEmployeeID(legacyIDToUUID("employee", empID)).
				SetMonthlySalary(parseDecimal(salary)).
				SetIncomeTax(orDefault(incomeTax, "primary"))
			if currency.Valid && currency.String != "" {
				c.SetCurrency(currency.String)
			}
			if bankAcct.Valid {
				c.SetBankAccountID(legacyIDToUUID("employee_bank_accounts", bankAcct.Int64))
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migrateContracts: employees_contract -> Contract. duration_months is recomputed by the
// service from start/end (data-migration §4), so the stale stored contract_duration (days)
// is not carried. salary is decimal. Tenant inherited from employee.
func (m *Migrator) migrateContracts() {
	m.guard("employees_contract", "contract", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, employee_id, contract_type, contract_start_date,
			contract_end_date, status, salary FROM employees_contract`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id, empID int64
			var ctype, status, salary sql.NullString
			var start, end sql.NullTime
			if err := rows.Scan(&id, &empID, &ctype, &start, &end, &status, &salary); err != nil {
				return st, err
			}
			st.read++
			tid, ok := m.employeeTenant(empID)
			if !ok {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("employees_contract", id)
			exists, err := m.client.Contract.Query().Where(contract.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.Contract.Create().
				SetID(newID).SetTenantID(tid).
				SetEmployeeID(legacyIDToUUID("employee", empID)).
				SetContractType(strOrEmpty(ctype)).
				SetStatus(orDefault(status, "active")).
				SetSalary(parseDecimal(salary))
			if dt := nairobiTime(start); dt != nil {
				c.SetStartDate(*dt)
			}
			if dt := nairobiTime(end); dt != nil {
				c.SetEndDate(*dt)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}
