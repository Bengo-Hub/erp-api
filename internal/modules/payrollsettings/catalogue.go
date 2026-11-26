package payrollsettings

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollcomponent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// Component categories (PayrollComponent.category).
const (
	CategoryEarnings   = "Earnings"
	CategoryDeductions = "Deductions"
	CategoryBenefits   = "Benefits"
)

// Who drives a module-managed component. Such a component is on by default because it only
// produces a payslip line when its own approved records exist (an approved overtime request, an
// issued loan, an approved claim); its amounts come from that module, not from the catalogue.
const (
	ManagedSalary        = "salary"
	ManagedAttendance    = "attendance"
	ManagedPieceRates    = "piece_rates"
	ManagedExpenseClaims = "expense_claims"
	ManagedLoans         = "loans"
	ManagedAdvances      = "advances"
	ManagedLossDamages   = "loss_damages"
	ManagedStaffPurchase = "staff_purchases"
	ManagedFormula       = "statutory_formula"
)

// CatalogueItem is one platform payroll component. Code is stored in PayrollComponent.wb_code
// and is the stable key tenants' choices refer to; codes reuse the engine and payslip line codes
// (paye, nssf, shif, housing_levy, nita, loans, advances, loss_damages, staff_purchase, overtime,
// holiday_pay, piece_work, expense_claim) so the catalogue, the engine and payslips agree.
type CatalogueItem struct {
	Code        string
	Title       string
	Category    string
	Statutory   bool
	ManagedBy   string
	Taxable     string // taxable | nontaxable | gratuity
	NonCash     bool
	Phase       string // deduction phase for deductions
	Priority    int
	Mode        string
	Percentage  string // default % of basic, "" for none
	Description string
}

// statutoryToggleOf maps a statutory component code to the engine code its tenant toggle governs.
var statutoryToggleOf = map[string]string{
	"paye":         payrollengine.CompPAYE,
	"nssf":         payrollengine.CompNSSF,
	"shif":         payrollengine.CompSHIF,
	"housing_levy": payrollengine.CompHousingLevy,
	"nita":         payrollengine.CompNITA,
}

// PlatformCatalogue is every common Kenyan earning, deduction and benefit. Statutory items are on
// for every tenant; module-managed items are on (they only appear when their module has approved
// records); everything else is opt-in per tenant.
func PlatformCatalogue() []CatalogueItem {
	e := func(code, title, managed, taxable, mode, desc string) CatalogueItem {
		return CatalogueItem{Code: code, Title: title, Category: CategoryEarnings, ManagedBy: managed, Taxable: taxable, Mode: mode, Description: desc}
	}
	d := func(code, title, managed, phase string, prio int, statutory bool, desc string) CatalogueItem {
		return CatalogueItem{Code: code, Title: title, Category: CategoryDeductions, ManagedBy: managed, Phase: phase,
			Priority: prio, Statutory: statutory, Taxable: "nontaxable", Mode: "monthly", Description: desc}
	}
	b := func(code, title, desc string) CatalogueItem {
		return CatalogueItem{Code: code, Title: title, Category: CategoryBenefits, Taxable: "taxable", NonCash: true, Mode: "monthly", Description: desc}
	}
	return []CatalogueItem{
		// Earnings.
		e("basic", "Basic Pay", ManagedSalary, "taxable", "monthly", "Monthly basic salary from each employee's salary details."),
		e("house_allowance", "House Allowance", "", "taxable", "monthly", "Cash housing allowance, taxable in full."),
		e("transport_allowance", "Transport Allowance", "", "taxable", "monthly", "Cash transport allowance, taxable."),
		e("commuter_allowance", "Commuter Allowance", "", "taxable", "monthly", "Commuter allowance, taxable."),
		e("airtime_allowance", "Airtime Allowance", "", "taxable", "monthly", "Airtime or communication allowance."),
		e("meal_allowance", "Meal Allowance", "", "taxable", "monthly", "Cash meal allowance."),
		e("hardship_allowance", "Hardship Allowance", "", "taxable", "monthly", "Hardship area allowance."),
		e("responsibility_allowance", "Responsibility Allowance", "", "taxable", "monthly", "Allowance for extra responsibilities."),
		e("acting_allowance", "Acting Allowance", "", "taxable", "monthly", "Allowance while acting in a higher role."),
		e("overtime", "Overtime", ManagedAttendance, "taxable", "perhour", "Approved overtime hours, paid when attendance settings pay overtime through payroll."),
		e("holiday_pay", "Holiday Work", ManagedAttendance, "taxable", "perhour", "Hours worked on public holidays at the holiday multiplier."),
		e("piece_work", "Piece Work", ManagedPieceRates, "taxable", "perpiece", "Approved piece output at the piece rates."),
		e("bonus", "Bonus", "", "taxable", "monthly", "Performance or annual bonus."),
		e("commission", "Commission", "", "taxable", "commission", "Sales commission."),
		e("leave_pay", "Leave Pay", "", "taxable", "monthly", "Leave allowance or pay for leave days."),
		e("arrears", "Salary Arrears", "", "taxable", "monthly", "Pay owed from earlier periods."),
		e("per_diem", "Per Diem", "", "nontaxable", "perday", "Daily subsistence while travelling on duty; the excess over the KRA limit is taxable."),
		e("expense_claim", "Expense Reimbursement", ManagedExpenseClaims, "nontaxable", "monthly", "Approved expense claims repaid with net pay."),
		e("gratuity", "Gratuity", "", "gratuity", "monthly", "Gratuity on contract end."),
		// Statutory deductions (rates come from the statutory formulas).
		d("paye", "P.A.Y.E.", ManagedFormula, payrollengine.PhaseAfterTax, 1, true, "Income tax from the PAYE formula."),
		d("nssf", "N.S.S.F.", ManagedFormula, payrollengine.PhaseBeforeTax, 1, true, "NSSF Tier I and II from the NSSF formula, matched by the employer."),
		d("shif", "S.H.I.F.", ManagedFormula, payrollengine.PhaseBeforeTax, 2, true, "Social Health Insurance Fund contribution."),
		d("housing_levy", "Affordable Housing Levy", ManagedFormula, payrollengine.PhaseBeforeTax, 3, true, "Housing levy, matched by the employer."),
		d("nita", "NITA Levy", ManagedFormula, payrollengine.PhaseFinal, 9, true, "Industrial training levy paid by the employer only."),
		// Recoveries driven by their own records.
		d("loans", "Staff Loan Repayment", ManagedLoans, payrollengine.PhaseAfterPAYE, 1, false, "Monthly installments of issued staff loans."),
		d("advances", "Salary Advance Recovery", ManagedAdvances, payrollengine.PhaseAfterPAYE, 2, false, "Recovery of salary advances when a run recovers advances."),
		d("loss_damages", "Losses and Damages", ManagedLossDamages, payrollengine.PhaseAfterPAYE, 3, false, "Recovery of recorded losses and damages."),
		d("staff_purchase", "Staff Purchases", ManagedStaffPurchase, payrollengine.PhaseAfterPAYE, 4, false, "Staff credit and layaway purchases funded from salary."),
		// Opt-in deductions.
		d("helb", "HELB Loan Repayment", "", payrollengine.PhaseAfterPAYE, 5, false, "Higher Education Loans Board repayment."),
		d("sacco", "SACCO Contribution", "", payrollengine.PhaseAfterPAYE, 6, false, "SACCO savings or loan check-off."),
		d("union_dues", "Union Dues", "", payrollengine.PhaseAfterPAYE, 7, false, "Trade union subscription."),
		d("pension", "Pension Contribution", "", payrollengine.PhaseBeforeTax, 4, false, "Registered pension scheme contribution, deductible up to the pension relief cap."),
		d("provident_fund", "Provident Fund", "", payrollengine.PhaseBeforeTax, 5, false, "Registered provident fund contribution."),
		d("post_retirement_medical", "Post-Retirement Medical Fund", "", payrollengine.PhaseAfterPAYE, 11, false, "Contribution to a registered post-retirement medical fund; deductible before tax up to the relief cap."),
		d("insurance_premium","Insurance Premium", "", payrollengine.PhaseAfterPAYE, 8, false, "Life, health or education policy premium; qualifies for insurance relief."),
		d("welfare", "Staff Welfare", "", payrollengine.PhaseAfterPAYE, 9, false, "Staff welfare contribution."),
		d("court_order", "Court Order or Garnishee", "", payrollengine.PhaseFinal, 1, false, "Deduction ordered by a court."),
		d("salary_overpayment", "Salary Overpayment Recovery", "", payrollengine.PhaseAfterPAYE, 10, false, "Recovery of pay made in error."),
		// Benefits in kind.
		b("car_benefit", "Company Car", "Private use of an employer-provided car."),
		b("housing_benefit", "Employer Housing", "Housing provided by the employer."),
		b("medical_cover", "Medical Cover", "Employer-paid medical insurance."),
		b("school_fees", "School Fees", "School fees paid by the employer."),
		b("meals_benefit", "Subsidised Meals", "Meals provided or subsidised by the employer."),
		b("utilities_benefit", "Utilities", "Electricity, water or internet paid by the employer."),
		b("security_benefit", "Security Services", "Security services provided at the employee's home."),
	}
}

// referenceLabels names the scheme or registration number an employee assignment of these opt-in
// deductions must carry (remittance schedules to HELB, SACCOs, unions, schemes and insurers list
// each employee by it). Components not listed take an optional reference.
var referenceLabels = map[string]string{
	"helb":              "HELB account number",
	"sacco":             "SACCO membership number",
	"union_dues":        "Union membership number",
	"pension":           "Pension scheme membership number",
	"provident_fund":    "Provident fund membership number",
	"insurance_premium": "Policy number",
	"court_order":       "Court case number",
}

// ReferenceLabel returns the label of the reference an employee assignment of the component code
// needs, or "" when none is required.
func ReferenceLabel(code string) string { return referenceLabels[code] }

var catalogueByCode = func() map[string]CatalogueItem {
	m := map[string]CatalogueItem{}
	for _, it := range PlatformCatalogue() {
		m[it.Code] = it
	}
	return m
}()

// EnsurePlatformCatalogue creates the catalogue components missing under the platform tenant.
// Idempotent: an existing code is left as it is, so platform edits survive redeploys.
func EnsurePlatformCatalogue(ctx context.Context, orm *ent.Client, systemTenant uuid.UUID) (int, error) {
	existing, err := orm.PayrollComponent.Query().
		Where(payrollcomponent.TenantID(systemTenant), payrollcomponent.WbCodeNotNil()).
		Select(payrollcomponent.FieldWbCode).Strings(ctx)
	if err != nil {
		return 0, err
	}
	have := map[string]bool{}
	for _, c := range existing {
		have[c] = true
	}
	created := 0
	for _, it := range PlatformCatalogue() {
		if have[it.Code] {
			continue
		}
		c := orm.PayrollComponent.Create().
			SetTenantID(systemTenant).
			SetWbCode(it.Code).
			SetTitle(it.Title).
			SetCategory(it.Category).
			SetDescription(it.Description).
			SetStatutory(it.Statutory).
			SetNonCash(it.NonCash).
			SetIsActive(true).
			SetTaxableStatus(it.Taxable)
		if it.Mode != "" {
			c = c.SetMode(it.Mode)
		}
		if it.Phase != "" {
			c = c.SetDeductionPhase(it.Phase)
		}
		if it.Priority > 0 {
			c = c.SetDeductionPriority(it.Priority)
		}
		if it.Percentage != "" {
			c = c.SetPercentage(decimal.RequireFromString(it.Percentage)).SetPercentOf("basic")
		}
		if _, err := c.Save(ctx); err != nil {
			return created, err
		}
		created++
	}
	return created, nil
}
