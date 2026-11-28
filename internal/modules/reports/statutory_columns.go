package reports

import (
	"time"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// Row keys of the statutory returns. They are the field names the erp-ui report pages read
// (src/lib/reports-config.ts), and the same keys drive the PDF/Excel/CSV export columns.
var (
	nssfColumns = []string{
		"employee_name", "employee_pin", "nssf_number", "gross_pay", "pensionable_earnings",
		"tier_1", "tier_2", "employee_total", "employer", "nssf_contribution",
	}
	nitaColumns = []string{"employee_name", "employee_pin", "gross_pay", "nita_levy"}
	// nssfUploadColumns is the NSSF employer portal's bulk upload, header for header: NSSF works
	// the tiers out itself from the pay. Taken from published guides; to be checked against the
	// template downloaded from selfservice.nssf.or.ke (decisions log row 44).
	nssfUploadColumns = []string{"PAYROLL NUMBER", "SURNAME", "OTHER NAMES", "ID NO", "KRA PIN", "NSSF NO", "GROSS PAY", "VOLUNTARY"}
)

// healthColumns is the SHIF/NHIF member schedule: who, their scheme number, gross and the
// contribution deducted.
func healthColumns(numberKey, amountKey string) []string {
	return []string{"employee_name", "employee_pin", "national_id", numberKey, "gross_pay", "gross_salary", amountKey, "coverage_type"}
}

func healthNumber(e *ent.Employee) string {
	if e == nil || e.ShifOrNhifNumber == nil {
		return ""
	}
	return *e.ShifOrNhifNumber
}

// shifStart is when SHIF replaced NHIF (Social Health Insurance Act, October 2024 payroll).
var shifStart = time.Date(2024, time.October, 1, 0, 0, 0, 0, time.UTC)

// coverageType names the health scheme a payslip's contribution went to.
func coverageType(p *ent.Payslip) string {
	if p.PaymentPeriod != nil && p.PaymentPeriod.Before(shifStart) {
		return "NHIF"
	}
	return "SHIF"
}
