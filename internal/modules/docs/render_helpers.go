package docs

import (
	"strings"

	"github.com/Bengo-Hub/erp-api/internal/modules/docs/builders"
	"github.com/shopspring/decimal"
)

// headerTitle returns the large title shown top-right.
func headerTitle(t DocType) string {
	switch t {
	case DocTypePayrollReport:
		return "Payroll Report"
	default:
		return "Payslip"
	}
}

// docTypeSubtitle returns the small caption shown under the document title.
func docTypeSubtitle(t DocType) string {
	switch t {
	case DocTypePayrollReport:
		return "PAYROLL & STATUTORY SCHEDULE"
	default:
		return "EMPLOYEE PAY STATEMENT"
	}
}

// partyLabels returns the (left, right) party-box headings for the document type.
func partyLabels(t DocType) (string, string) {
	switch t {
	case DocTypePayrollReport:
		return "REPORT FOR", "PREPARED BY"
	default:
		return "EMPLOYEE", "EMPLOYER"
	}
}

// amountLabel returns the banner amount caption (unused by ERP docs but kept for the
// shared renderer).
func amountLabel(d *Document) string {
	if d.AmountLabel != "" {
		return d.AmountLabel
	}
	return "Net Pay"
}

// grandTotalLabel returns the label used inside the gradient grand-total bar.
func grandTotalLabel(d *Document) string {
	if lbl := profileFor(d.Type).grandTotalLabel; lbl != "" {
		return lbl
	}
	return "Grand Total"
}

// badgeText returns the status badge text (explicit override, else default).
func badgeText(d *Document) string {
	if d.Badge != "" {
		return strings.ToUpper(d.Badge)
	}
	return strings.ToUpper(d.Status)
}

// metaRows builds the right-hand meta box rows, skipping empty values.
func metaRows(d *Document) [][2]string {
	title := headerTitle(d.Type)
	rows := [][2]string{
		{title + " No.", ifEmpty(d.DocNumber, "—")},
	}
	if d.PeriodLabel != "" {
		rows = append(rows, [2]string{"Period", d.PeriodLabel})
	} else {
		rows = append(rows, [2]string{title + " Date", builders.FormatDate(d.DocDate)})
	}
	if d.EmployeeNumber != "" {
		rows = append(rows, [2]string{"Staff No.", d.EmployeeNumber})
	}
	if d.PaymentDate != "" {
		rows = append(rows, [2]string{"Pay Date", d.PaymentDate})
	}
	if d.Reference != "" {
		rows = append(rows, [2]string{"Reference", d.Reference})
	}
	if d.Currency != "" {
		rows = append(rows, [2]string{"Currency", d.Currency})
	}
	return rows
}

// issuerContactLines builds the right party box contact lines (issuer email / phone /
// website) for the tenant.
func issuerContactLines(d *Document) []string {
	out := []string{}
	if d.TenantEmail != "" {
		out = append(out, d.TenantEmail)
	}
	if d.TenantPhone != "" {
		out = append(out, d.TenantPhone)
	}
	if d.TenantWebsite != "" {
		out = append(out, d.TenantWebsite)
	}
	return out
}

// companyAddressLines splits the tenant address into display lines and appends the
// country. Splits on newlines or commas, capping at three lines.
func companyAddressLines(d *Document) []string {
	lines := splitLines(d.TenantAddress)
	if d.TenantCountry != "" {
		lines = append(lines, d.TenantCountry)
	}
	if len(lines) > 3 {
		lines = lines[:3]
	}
	return lines
}

// companyAddressText returns the issuer address for the company block, preserving any
// line breaks the user entered and appending the country on its own line.
func companyAddressText(d *Document) string {
	addr := strings.TrimSpace(d.TenantAddress)
	if c := displayCountry(d.TenantCountry); c != "" && !strings.HasSuffix(strings.ToLower(addr), strings.ToLower(c)) {
		if addr != "" {
			addr += "\n"
		}
		addr += c
	}
	return addr
}

// displayCountry returns a country string fit to print: empty for blank or 2-3 letter
// ISO codes; full names pass through.
func displayCountry(c string) string {
	c = strings.TrimSpace(c)
	if len(c) <= 3 {
		return ""
	}
	return c
}

// customerAddressLines splits the subject (employee) address into display lines.
func customerAddressLines(d *Document) []string {
	lines := splitLines(d.CustomerAddress)
	if c := displayCountry(d.CustomerCountry); c != "" {
		lines = append(lines, c)
	}
	if len(lines) > 3 {
		lines = lines[:3]
	}
	return lines
}

// partyContactLines returns the subject contact lines: designation, email, phone, Tax PIN.
func partyContactLines(d *Document) []string {
	out := []string{}
	if d.EmployeeTitle != "" {
		out = append(out, d.EmployeeTitle)
	}
	if d.CustomerEmail != "" {
		out = append(out, d.CustomerEmail)
	}
	if d.CustomerPhone != "" {
		out = append(out, d.CustomerPhone)
	}
	if d.CustomerTaxPin != "" {
		out = append(out, "KRA PIN: "+d.CustomerTaxPin)
	}
	return out
}

// notesLines returns the notes/terms entries as bullet lines.
func notesLines(d *Document) []string {
	out := []string{}
	if d.Notes != "" {
		out = append(out, d.Notes)
	}
	if d.Terms != "" {
		out = append(out, d.Terms)
	}
	return out
}

// money formats an amount as "CODE 1,234.56" using the currency code prefix.
func money(currency string, v decimal.Decimal) string {
	return currencyCode(currency) + " " + builders.FormatFloat(v.InexactFloat64())
}

// currencyCode returns the leading token of a currency string.
func currencyCode(currency string) string {
	fields := strings.Fields(currency)
	if len(fields) > 0 {
		return fields[0]
	}
	return currency
}

// trimDecimal renders a decimal with no trailing zeros (e.g. "2", "2.5").
func trimDecimal(d decimal.Decimal) string {
	s := d.StringFixed(2)
	s = strings.TrimRight(s, "0")
	s = strings.TrimRight(s, ".")
	if s == "" {
		return "0"
	}
	return s
}

// splitLines splits a free-form address on newlines (preferred) or commas.
func splitLines(s string) []string {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	var raw []string
	if strings.ContainsAny(s, "\r\n") {
		raw = strings.FieldsFunc(s, func(r rune) bool { return r == '\n' || r == '\r' })
	} else {
		raw = strings.Split(s, ",")
	}
	out := make([]string, 0, len(raw))
	for _, ln := range raw {
		if t := strings.TrimSpace(ln); t != "" {
			out = append(out, t)
		}
	}
	return out
}

// imgType returns the fpdf image-type string for the given raw image bytes.
func imgType(b []byte) string {
	switch {
	case len(b) >= 3 && b[0] == 0xFF && b[1] == 0xD8 && b[2] == 0xFF:
		return "JPG"
	case len(b) >= 4 && b[0] == 0x47 && b[1] == 0x49 && b[2] == 0x46:
		return "GIF"
	default:
		return "PNG"
	}
}
