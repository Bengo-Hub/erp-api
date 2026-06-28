package adapters

import (
	"github.com/Bengo-Hub/erp-api/internal/modules/docs"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

// PayslipInput is the employee/period identity the payslip PDF needs on top of the
// money breakdown (which is the shared payroll.PayslipBreakdown — single source of truth).
type PayslipInput struct {
	DocNumber      string
	EmployeeName   string
	EmployeeNumber string
	EmployeeTitle  string
	EmployeeEmail  string
	EmployeePhone  string
	EmployeeKraPin string
	PeriodLabel    string // e.g. "April 2026"
	PaymentDate    string // formatted disbursement date (optional)
	Currency       string // empty → "KES"
	Status         string // payslip status badge (optional)
	Bank           *docs.BankDetails
	// Personal info (statutory + payment identity).
	NationalID  string
	ShifNumber  string
	NssfNumber  string
	PaymentMode string
	Department  string
	Region      string
	CreatedDate string
}

// PayslipToDocument converts the shared payslip breakdown + employee identity + tenant
// branding into the generic Document model the renderer consumes. The earnings and
// deductions rows come straight from payroll.BuildPayslipBreakdown so the PDF and the
// JSON view never diverge.
func PayslipToDocument(in PayslipInput, b payroll.PayslipBreakdown, ti TenantInfo) *docs.Document {
	currency := in.Currency
	if currency == "" {
		currency = "KES"
	}

	earnings := make([]docs.AmountRow, 0, len(b.Earnings))
	for _, e := range b.Earnings {
		earnings = append(earnings, docs.AmountRow{Label: e.Label, Amount: e.Amount})
	}
	deductions := make([]docs.AmountRow, 0, len(b.Deductions))
	for _, dd := range b.Deductions {
		deductions = append(deductions, docs.AmountRow{Label: dd.Label, Amount: dd.Amount})
	}

	bank := in.Bank
	if bank != nil && bank.IsEmpty() {
		bank = nil
	}

	return withBranding(&docs.Document{
		Type:           docs.DocTypePayslip,
		DocNumber:      in.DocNumber,
		TenantName:     ti.Name,
		TenantSlug:     ti.Slug,
		TenantEmail:    ti.Email,
		TenantPhone:    ti.Phone,
		TenantAddress:  ti.Address,
		TenantCountry:  ti.Country,
		TenantWebsite:  ti.Website,
		TenantLogoURL:  ti.LogoURL,
		TenantPrimaryColor: ti.PrimaryColor,

		CustomerName:   in.EmployeeName,
		CustomerEmail:  in.EmployeeEmail,
		CustomerPhone:  in.EmployeePhone,
		CustomerTaxPin: in.EmployeeKraPin,

		EmployeeNumber: in.EmployeeNumber,
		EmployeeTitle:  in.EmployeeTitle,
		PeriodLabel:    in.PeriodLabel,
		PaymentDate:    in.PaymentDate,
		Status:         in.Status,

		EmployeeNationalID:  in.NationalID,
		EmployeeShif:        in.ShifNumber,
		EmployeeNssf:        in.NssfNumber,
		EmployeePaymentMode: in.PaymentMode,
		EmployeeDepartment:  in.Department,
		EmployeeRegion:      in.Region,
		CreatedDate:         in.CreatedDate,

		BankDetails: bank,

		Earnings:   earnings,
		Deductions: deductions,

		Subtotal:    b.TotalEarnings,
		TotalAmount: b.NetPay,
		Currency:    currency,
	}, ti)
}
