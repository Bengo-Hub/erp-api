package docs

// templateProfile drives which sections the shared base renderer emits for a given
// document type. The base pipeline (header, company/meta strip, parties, signatures,
// footer) is shared by EVERY document; the profile selects the per-type body so each
// renders the right sections — e.g. a payslip drops the How-to-Pay/amount banner and
// renders an earnings-vs-deductions two-column body with a "Net Pay" grand total,
// while a payroll report renders a tabular schedule with no banner.
type templateProfile struct {
	showAmountBanner bool   // gradient "amount" banner with status badge
	showTotals       bool   // grand-total block + amount-in-words
	showHowToPay     bool   // bank / pay-online block (non-ERP docs)
	showDueDate      bool   // "Due Date" / period row in the meta box
	receiverSignoff  bool   // signature band shows "Delivered By" / "Received By"
	acknowledgement  string // line rendered above the body when non-empty
	grandTotalLabel  string // overrides the gradient grand-total label (empty = default)

	payslipBody bool // render the payslip earnings/deductions two-column body
	reportBody  bool // render the payroll-report tabular schedule body
}

// profileFor returns the template profile for a document type.
func profileFor(t DocType) templateProfile {
	switch t {
	case DocTypePayslip:
		// A payslip is a confidential pay statement: no How-to-Pay, no amount banner;
		// an employee identity block, a two-column earnings/deductions breakdown and a
		// "Net Pay" grand total.
		return templateProfile{
			showAmountBanner: false,
			showTotals:       true,
			showHowToPay:     false,
			showDueDate:      false,
			grandTotalLabel:  "Net Pay",
			payslipBody:      true,
		}
	case DocTypePayrollReport:
		// A payroll/statutory report is a tabular schedule: no banner, no payment block.
		return templateProfile{
			showAmountBanner: false,
			showTotals:       false,
			showHowToPay:     false,
			showDueDate:      false,
			reportBody:       true,
		}
	case DocTypePaymentVoucher:
		// A consultant payment voucher: amount banner with the NET, a line breakdown
		// (gross fee, WHT, deductions) and a "Net Amount" grand total. No How-to-Pay block.
		return templateProfile{
			showAmountBanner: true,
			showTotals:       true,
			showHowToPay:     false,
			showDueDate:      true,
			grandTotalLabel:  "Net Amount",
		}
	default:
		return templateProfile{showAmountBanner: true, showTotals: true, showHowToPay: true, showDueDate: true}
	}
}
