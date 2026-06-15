// Package docs provides backend document generation (PDF, CSV, XLSX) for ERP HR
// documents — payslips and payroll/statutory reports. The generic renderer,
// palette, painter and Format dispatcher are adapted from treasury-api's docs
// module; the ERP keeps only the document types it owns (payslip, payroll_report).
package docs

import (
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// BankDetails holds payment / banking information (employee bank account on a payslip).
type BankDetails struct {
	AccountName   string
	AccountNumber string
	BankName      string
	BranchCode    string // IBAN / branch / swift code
	MpesaPaybill  string
	MpesaTill     string
}

// IsEmpty returns true when no bank fields are populated.
func (b *BankDetails) IsEmpty() bool {
	if b == nil {
		return true
	}
	return b.AccountName == "" && b.AccountNumber == "" && b.BankName == "" &&
		b.MpesaPaybill == "" && b.MpesaTill == ""
}

// DocType identifies the kind of ERP document.
type DocType string

const (
	DocTypePayslip       DocType = "payslip"
	DocTypePayrollReport DocType = "payroll_report"
)

// DocumentLine is a single line item shared across document types (used by the
// report tabular schedule and the export formats).
type DocumentLine struct {
	SortOrder      int
	Description    string
	Quantity       decimal.Decimal
	UnitPrice      decimal.Decimal
	TaxRate        decimal.Decimal
	TaxAmount      decimal.Decimal
	DiscountAmount decimal.Decimal
	LineTotal      decimal.Decimal
}

// AmountRow is a labelled money row used by the payslip earnings/deductions columns.
type AmountRow struct {
	Label  string
	Amount decimal.Decimal
}

// Document is the canonical input model for all document generators. Handlers map
// their domain models to this before calling generators.
type Document struct {
	Type        DocType
	DocNumber   string
	PublicToken uuid.UUID

	// Sender (tenant)
	TenantName    string
	TenantSlug    string
	TenantEmail   string
	TenantPhone   string
	TenantAddress string

	// Sender logo (fetched from auth-api branding; empty = no logo in PDF)
	TenantLogoURL string

	// Extended sender branding (from auth-api branding)
	TenantCountry      string
	TenantWebsite      string
	TenantPrimaryColor string // hex e.g. "#6366f1"; empty = use default indigo

	// Bank / payment details (employee bank account on a payslip; optional)
	BankDetails *BankDetails

	// PayURL / PaymentInstructions are payment-request fields (unused by ERP docs).
	PayURL              string
	PaymentInstructions string

	// Recipient / subject (the employee on a payslip)
	CustomerName          string
	CustomerEmail         string
	CustomerPhone         string
	CustomerAddress       string
	CustomerCountry       string
	CustomerTaxPin        string // employee KRA / tax PIN
	CustomerContactPerson string

	// Dates
	DocDate    time.Time
	ValidUntil time.Time

	// Totals
	Subtotal       decimal.Decimal
	TaxAmount      decimal.Decimal
	DiscountAmount decimal.Decimal
	TotalAmount    decimal.Decimal
	Currency       string

	// Content
	Lines  []DocumentLine
	Notes  string
	Terms  string
	Status string

	// ── Premium-template optional fields ──────────────────────────────────────
	Tagline   string // tenant tagline shown under the company name
	TaxPIN    string // KRA / tax PIN of the issuer (e.g. "P051565369U")
	Reference string // reference number

	AmountLabel string // banner label; empty → default by document type
	Badge       string // status badge text; empty → default by type/status

	PreparedBy string // signatory (left signature line)
	ApprovedBy string // signatory (right signature line)

	// Delivery / acknowledgement (unused by ERP docs but kept for the shared renderer)
	AcknowledgementText string
	ReceiverSignoff     bool

	// ── Payslip-specific (rendered only for payslips) ─────────────────────────
	// Identity block (employee number, designation, period label, payment date).
	EmployeeNumber  string
	EmployeeTitle   string
	PeriodLabel     string // e.g. "April 2026"
	PaymentDate     string // formatted disbursement date (optional)

	// Two-column earnings vs deductions breakdown.
	Earnings   []AmountRow
	Deductions []AmountRow

	// ── Report-specific (rendered only for payroll reports) ───────────────────
	// ReportColumns / ReportRows drive the tabular schedule, and ReportTotals is a
	// labelled footer row. All values are pre-formatted strings.
	ReportTitle   string
	ReportColumns []string
	ReportRows    [][]string
	ReportTotals  []string

	// Receipt payment block (unused by ERP docs).
	AgainstInvoice   string
	PaymentMethod    string
	PaymentValueDate string
	PaymentRef       string
	PaymentSwiftRef  string
	PaymentRemarks   string
}

// LineHeaders are the column headings for line items in export formats.
var LineHeaders = []string{
	"#", "Description", "Quantity", "Unit Price", "Tax Rate (%)", "Tax Amount", "Discount", "Total",
}

func docTypeTitle(t DocType) string {
	switch t {
	case DocTypePayrollReport:
		return "Payroll Report"
	default:
		return "Payslip"
	}
}

func ifEmpty(s, fallback string) string {
	if s == "" {
		return fallback
	}
	return s
}

// ToRows converts document lines to string rows for CSV/XLSX export.
func (d *Document) ToRows() [][]string {
	rows := make([][]string, len(d.Lines))
	for i, l := range d.Lines {
		rows[i] = []string{
			fmt.Sprintf("%d", i+1),
			l.Description,
			l.Quantity.StringFixed(2),
			l.UnitPrice.StringFixed(2),
			l.TaxRate.StringFixed(2),
			l.TaxAmount.StringFixed(2),
			l.DiscountAmount.StringFixed(2),
			l.LineTotal.StringFixed(2),
		}
	}
	return rows
}
