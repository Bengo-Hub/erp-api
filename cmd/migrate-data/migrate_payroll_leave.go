package main

import (
	"database/sql"

	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
)

// migratePayslips: payslips -> Payslip. The golden-master parity table — ALL money columns
// are carried as exact decimals (never float). Effective amounts are preserved exactly so the
// payroll golden-master check (re-run the Go engine, compare net/PAYE/NSSF/SHIF) can validate
// against the migrated values. Tenant inherited from employee.
func (m *Migrator) migratePayslips() {
	m.guard("payslips", "payslip", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, employee_id,
			gross_pay, total_earnings, net_pay,
			taxable_pay, paye, tax_relief, reliefs, gross_pay_after_tax,
			shif_or_nhif_contribution, housing_levy,
			nssf_employee_tier_1, nssf_employee_tier_2, nssf_employer_contribution,
			deductions_before_tax, deductions_after_tax, deductions_after_paye, deductions_final,
			payment_period, payroll_status, approval_status, published,
			period_start, period_end, kra_paye_reference, kra_filed_at, delete_status
			FROM payslips`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id, empID int64
			var grossPay, totalEarn, netPay, taxablePay, paye, taxRelief, reliefs, gpat,
				shif, housing, nssf1, nssf2, nssfEmp,
				dbt, dat, dapaye, dfinal sql.NullString
			var paymentPeriod, periodStart, periodEnd, kraFiledAt sql.NullTime
			var payrollStatus, approvalStatus, kraRef sql.NullString
			var published, deleteStatus sql.NullBool
			if err := rows.Scan(&id, &empID,
				&grossPay, &totalEarn, &netPay,
				&taxablePay, &paye, &taxRelief, &reliefs, &gpat,
				&shif, &housing, &nssf1, &nssf2, &nssfEmp,
				&dbt, &dat, &dapaye, &dfinal,
				&paymentPeriod, &payrollStatus, &approvalStatus, &published,
				&periodStart, &periodEnd, &kraRef, &kraFiledAt, &deleteStatus); err != nil {
				return st, err
			}
			st.read++
			tid, ok := m.employeeTenant(empID)
			if !ok {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("payslips", id)
			exists, err := m.client.Payslip.Query().Where(payslip.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.Payslip.Create().
				SetID(newID).SetTenantID(tid).
				SetEmployeeID(legacyIDToUUID("employee", empID)).
				SetGrossPay(parseDecimal(grossPay)).
				SetTotalEarnings(parseDecimal(totalEarn)).
				SetNetPay(parseDecimal(netPay)).
				SetTaxablePay(parseDecimal(taxablePay)).
				SetPaye(parseDecimal(paye)).
				SetTaxRelief(parseDecimal(taxRelief)).
				SetReliefs(parseDecimal(reliefs)).
				SetGrossPayAfterTax(parseDecimal(gpat)).
				SetShifOrNhifContribution(parseDecimal(shif)).
				SetHousingLevy(parseDecimal(housing)).
				SetNssfEmployeeTier1(parseDecimal(nssf1)).
				SetNssfEmployeeTier2(parseDecimal(nssf2)).
				SetNssfEmployerContribution(parseDecimal(nssfEmp)).
				SetDeductionsBeforeTax(parseDecimal(dbt)).
				SetDeductionsAfterTax(parseDecimal(dat)).
				SetDeductionsAfterPaye(parseDecimal(dapaye)).
				SetDeductionsFinal(parseDecimal(dfinal)).
				SetPayrollStatus(orDefault(payrollStatus, "queued")).
				SetApprovalStatus(orDefault(approvalStatus, "draft")).
				SetPublished(boolOr(published, false)).
				SetDeleteStatus(boolOr(deleteStatus, false))
			if dt := nairobiTime(paymentPeriod); dt != nil {
				c.SetPaymentPeriod(*dt)
			}
			if dt := nairobiTime(periodStart); dt != nil {
				c.SetPeriodStart(*dt)
			}
			if dt := nairobiTime(periodEnd); dt != nil {
				c.SetPeriodEnd(*dt)
			}
			if p := strPtr(kraRef); p != nil {
				c.SetKraPayeReference(*p)
			}
			if dt := nairobiTime(kraFiledAt); dt != nil {
				c.SetKraFiledAt(*dt)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// migrateLeaveRequests: leave_leaverequest -> LeaveRequest. category remaps to the migrated
// LeaveCategory UUID; approved_by (Django Employee FK) remaps to the migrated employee UUID.
// status maps to the Ent enum (pending|approved|rejected|cancelled). Tenant from employee.
func (m *Migrator) migrateLeaveRequests() {
	m.guard("leave_leaverequest", "leave_request", func() (tableStat, error) {
		var st tableStat
		rows, err := m.query(`SELECT id, employee_id, category_id, start_date, end_date,
			days_requested, reason, status, approved_by_id, approved_at, rejection_reason
			FROM leave_leaverequest`)
		if err != nil {
			return st, err
		}
		defer func() { _ = rows.Close() }()
		for rows.Next() {
			var id, empID, catID int64
			var approvedBy sql.NullInt64
			var days, reason, status, rejection sql.NullString
			var start, end, approvedAt sql.NullTime
			if err := rows.Scan(&id, &empID, &catID, &start, &end, &days, &reason,
				&status, &approvedBy, &approvedAt, &rejection); err != nil {
				return st, err
			}
			st.read++
			tid, ok := m.employeeTenant(empID)
			if !ok {
				st.skipped++
				continue
			}
			newID := legacyIDToUUID("leave_leaverequest", id)
			exists, err := m.client.LeaveRequest.Query().Where(leaverequest.IDEQ(newID)).Exist(m.ctx)
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
			c := m.client.LeaveRequest.Create().
				SetID(newID).SetTenantID(tid).
				SetEmployeeID(legacyIDToUUID("employee", empID)).
				SetCategoryID(legacyIDToUUID("leave_leavecategory", catID)).
				SetDaysRequested(parseDecimal(days)).
				SetReason(strOrEmpty(reason)).
				SetStatus(leaveStatus(strOrEmpty(status)))
			if start.Valid {
				c.SetStartDate(*nairobiTime(start))
			}
			if end.Valid {
				c.SetEndDate(*nairobiTime(end))
			}
			if approvedBy.Valid {
				c.SetApprovedBy(legacyIDToUUID("employee", approvedBy.Int64))
			}
			if dt := nairobiTime(approvedAt); dt != nil {
				c.SetApprovedAt(*dt)
			}
			if r := strPtr(rejection); r != nil {
				c.SetRejectionReason(*r)
			}
			if err := c.Exec(m.ctx); err != nil {
				return st, err
			}
			st.written++
		}
		return st, rows.Err()
	})
}

// leaveStatus maps the legacy free-text status to the Ent enum, defaulting unknown values to
// pending (the safe non-terminal state).
func leaveStatus(s string) leaverequest.Status {
	switch s {
	case "approved":
		return leaverequest.StatusApproved
	case "rejected":
		return leaverequest.StatusRejected
	case "cancelled", "canceled":
		return leaverequest.StatusCancelled
	default:
		return leaverequest.StatusPending
	}
}
