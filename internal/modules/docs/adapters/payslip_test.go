package adapters

import (
	"testing"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/docs"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

func dec(v float64) decimal.Decimal { return decimal.NewFromFloat(v) }

// TestPayslipToDocument verifies the payslip adapter maps the breakdown + identity +
// branding onto the Document fields the renderer reads, with no figure drift.
func TestPayslipToDocument(t *testing.T) {
	b := payroll.PayslipBreakdown{
		GrossPay:      dec(100000),
		BasicSalary:   dec(100000),
		TotalEarnings: dec(100000),
		PAYE:          dec(20000),
		NSSF:          dec(2160),
		SHIF:          dec(2750),
		HousingLevy:   dec(1500),
		NetPay:        dec(73590),
		Earnings:      []payroll.AmountItem{{Label: "Gross Pay", Amount: dec(100000)}},
		Deductions: []payroll.AmountItem{
			{Label: "PAYE", Amount: dec(20000)},
			{Label: "NSSF", Amount: dec(2160)},
			{Label: "SHIF / NHIF", Amount: dec(2750)},
			{Label: "Housing Levy", Amount: dec(1500)},
		},
	}
	in := PayslipInput{
		DocNumber:      "PAY-260615-000001",
		EmployeeName:   "Jane Doe",
		EmployeeNumber: "EMP-007",
		EmployeeKraPin: "A001234567Z",
		PeriodLabel:    "April 2026",
	}
	ti := FromBranding("acme", &BrandingData{
		Name: "Acme Ltd", Slug: "acme", PrimaryColor: "#1f6fb2", KraPin: "P051565369U", Address: "Nairobi",
	})

	d := PayslipToDocument(in, b, ti)

	if d.Type != docs.DocTypePayslip {
		t.Fatalf("type = %q, want payslip", d.Type)
	}
	if d.DocNumber != "PAY-260615-000001" {
		t.Errorf("doc number = %q", d.DocNumber)
	}
	if d.CustomerName != "Jane Doe" || d.EmployeeNumber != "EMP-007" {
		t.Errorf("identity mismatch: name=%q number=%q", d.CustomerName, d.EmployeeNumber)
	}
	if d.CustomerTaxPin != "A001234567Z" {
		t.Errorf("employee KRA pin = %q", d.CustomerTaxPin)
	}
	if d.PeriodLabel != "April 2026" {
		t.Errorf("period = %q", d.PeriodLabel)
	}
	if !d.TotalAmount.Equal(dec(73590)) {
		t.Errorf("net pay (TotalAmount) = %s, want 73590", d.TotalAmount)
	}
	if d.Currency != "KES" {
		t.Errorf("currency = %q, want KES (default)", d.Currency)
	}
	if len(d.Earnings) != 1 || !d.Earnings[0].Amount.Equal(dec(100000)) {
		t.Errorf("earnings rows = %+v", d.Earnings)
	}
	if len(d.Deductions) != 4 {
		t.Fatalf("deductions rows = %d, want 4", len(d.Deductions))
	}
	if d.Deductions[0].Label != "PAYE" || !d.Deductions[0].Amount.Equal(dec(20000)) {
		t.Errorf("first deduction = %+v", d.Deductions[0])
	}
	// Branding mapped through.
	if d.TenantName != "Acme Ltd" || d.TenantPrimaryColor != "#1f6fb2" || d.TaxPIN != "P051565369U" {
		t.Errorf("branding mismatch: name=%q color=%q pin=%q", d.TenantName, d.TenantPrimaryColor, d.TaxPIN)
	}
}

// TestPayslipPDFRenders confirms the adapter output renders to a valid PDF end-to-end.
func TestPayslipPDFRenders(t *testing.T) {
	b := payroll.PayslipBreakdown{
		GrossPay: dec(50000), TotalEarnings: dec(50000), NetPay: dec(40000),
		Earnings:   []payroll.AmountItem{{Label: "Gross Pay", Amount: dec(50000)}},
		Deductions: []payroll.AmountItem{{Label: "PAYE", Amount: dec(10000)}},
	}
	d := PayslipToDocument(PayslipInput{DocNumber: "PAY-1", EmployeeName: "T. Test", PeriodLabel: "May 2026"}, b,
		FromBranding("acme", &BrandingData{Name: "Acme Ltd"}))
	out, _, err := (&docs.DocumentService{}).Generate(d, docs.FormatPDF)
	if err != nil {
		t.Fatalf("generate pdf: %v", err)
	}
	if len(out) < 4 || string(out[:4]) != "%PDF" {
		t.Fatalf("output is not a PDF (len=%d)", len(out))
	}
}
