package employees

import (
	"bytes"
	"context"
	"fmt"
	"html"
	"io"
	"net/http"
	"strings"

	"github.com/go-pdf/fpdf"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/contract"
)

// This file implements tenant-scoped, editable employment-contract content:
//   1. a DEFAULT employment-terms HTML body generated from tenant + employee + employment type
//      (director/shareholder remuneration + exit follow the Companies Act 2015; permanent staff
//      follow the Employment Act 2007), and
//   2. a branded PDF renderer that reuses the go-pdf/fpdf engine (the same library the docs
//      module uses) — company letterhead + the HTML body via a basic HTML writer + signatures.
//
// fpdf's built-in HTMLBasic writer only understands <b>/<i>/<u>/<br>/<a>. The block tags this
// module emits (<h3>/<p>/<ul>/<li>) are rendered by renderHTMLBody below, which tokenizes with
// fpdf.HTMLBasicTokenize and degrades unknown tags gracefully (see NOTE at renderHTMLBody).

// Employment types (drive the remuneration + termination/exit clauses).
const (
	EmploymentDirector            = "director"
	EmploymentShareholder         = "shareholder"
	EmploymentDirectorShareholder = "director_shareholder"
	EmploymentPermanent           = "permanent"
	EmploymentContractor          = "contractor"
	EmploymentCasual              = "casual"
	EmploymentInternship          = "internship"
)

// NormalizeEmploymentType resolves an employment type from the query param, falling back to the
// employee's governance flags, then to "permanent".
func NormalizeEmploymentType(t string, isDirector, isShareholder bool) string {
	switch strings.ToLower(strings.TrimSpace(t)) {
	case EmploymentDirector:
		return EmploymentDirector
	case EmploymentShareholder:
		return EmploymentShareholder
	case EmploymentDirectorShareholder:
		return EmploymentDirectorShareholder
	case EmploymentPermanent:
		return EmploymentPermanent
	case EmploymentContractor:
		return EmploymentContractor
	case EmploymentCasual:
		return EmploymentCasual
	case EmploymentInternship:
		return EmploymentInternship
	}
	switch {
	case isDirector && isShareholder:
		return EmploymentDirectorShareholder
	case isDirector:
		return EmploymentDirector
	case isShareholder:
		return EmploymentShareholder
	default:
		return EmploymentPermanent
	}
}

// ContractTermsInput carries everything the default-terms builder + PDF renderer need. The
// tenant fields come from auth-api branding (BrandingClient.GetBySlug); the employee fields
// from the Employee row.
type ContractTermsInput struct {
	// Tenant / company (branding)
	CompanyName    string
	CompanyAddress string
	CompanyKraPin  string
	PrimaryColor   string // hex e.g. "#6366f1"; empty → default indigo
	LogoURL        string

	// Employee
	EmployeeName  string
	JobTitle      string
	IsDirector    bool
	IsShareholder bool

	// EmploymentType — one of the Employment* constants.
	EmploymentType string
}

func (in ContractTermsInput) companyName() string  { return firstNonBlank(in.CompanyName, "The Company") }
func (in ContractTermsInput) employeeName() string { return firstNonBlank(in.EmployeeName, "The Employee") }

func (in ContractTermsInput) roleTitle() string {
	if in.JobTitle != "" {
		return in.JobTitle
	}
	switch in.EmploymentType {
	case EmploymentDirector, EmploymentDirectorShareholder:
		return "Director"
	case EmploymentShareholder:
		return "Shareholder"
	case EmploymentInternship:
		return "Intern"
	case EmploymentContractor:
		return "Independent Contractor"
	case EmploymentCasual:
		return "Casual Worker"
	default:
		return "Employee"
	}
}

// BuildDefaultTermsHTML builds the default employment-terms HTML body for the given tenant +
// employee + employment type. Output is clean semantic HTML (h3/p/b/ul/li).
func BuildDefaultTermsHTML(in ContractTermsInput) string {
	company := esc(in.companyName())
	name := esc(in.employeeName())
	role := esc(in.roleTitle())

	var b strings.Builder
	p := func(s string) { b.WriteString("<p>" + s + "</p>") }
	h := func(s string) { b.WriteString("<h3>" + s + "</h3>") }

	p(fmt.Sprintf("These Terms of Engagement are entered into between <b>%s</b> (\"the Company\") and <b>%s</b> (\"the %s\"), and set out the terms on which the %s is engaged.",
		company, name, appointee(in.EmploymentType), strings.ToLower(appointee(in.EmploymentType))))

	h("1. Position and Duties")
	p(fmt.Sprintf("The %s is engaged in the position of <b>%s</b>. The %s shall discharge the duties, responsibilities and functions reasonably associated with the position and such other lawful duties as may be assigned from time to time, and shall act in good faith and in the best interests of the Company.",
		appointee(in.EmploymentType), role, appointee(in.EmploymentType)))

	h("2. Commencement")
	p("This engagement commences on the date of signature of these terms (or such other date as the parties agree in writing) and, unless stated otherwise below, continues until terminated in accordance with these terms.")

	h("3. Place of Engagement")
	p(fmt.Sprintf("The principal place of engagement is the Company's registered/place of business%s. The %s may be required to work at or travel to such other places as the business reasonably requires.",
		addressClause(in.CompanyAddress), appointee(in.EmploymentType)))

	// Remuneration + termination/exit vary by type.
	h("4. Remuneration")
	b.WriteString(remunerationClause(in))

	h("5. Confidentiality")
	p(fmt.Sprintf("The %s shall keep confidential all trade secrets, financial information, customer and supplier data, and other proprietary or confidential information of the Company, both during the engagement and after it ends, and shall not use or disclose such information except as required to perform the role or as required by law.",
		appointee(in.EmploymentType)))

	h("6. Intellectual Property")
	p(fmt.Sprintf("All intellectual property, works, inventions and materials created by the %s in the course of the engagement, or using the Company's resources, are the sole property of the Company. The %s hereby assigns to the Company all such rights and shall execute any documents reasonably required to give effect to this assignment.",
		appointee(in.EmploymentType), appointee(in.EmploymentType)))

	h("7. Data Protection")
	p(fmt.Sprintf("The Company processes personal data of the %s in accordance with the <b>Data Protection Act, 2019</b>, solely for legitimate engagement, payroll, statutory and administrative purposes, and applies appropriate safeguards. The %s consents to such processing for those purposes.",
		appointee(in.EmploymentType), appointee(in.EmploymentType)))

	h("8. Termination / Exit")
	b.WriteString(terminationClause(in))

	h("9. Governing Law")
	p("These terms are governed by and construed in accordance with the laws of the <b>Republic of Kenya</b>, and the parties submit to the jurisdiction of the Kenyan courts.")

	p("<b>IN WITNESS WHEREOF</b> the parties have executed these terms on the dates set out below.")

	return b.String()
}

// appointee returns the party noun used throughout the clauses for the given type.
func appointee(t string) string {
	switch t {
	case EmploymentDirector, EmploymentDirectorShareholder:
		return "Director"
	case EmploymentShareholder:
		return "Shareholder"
	case EmploymentContractor:
		return "Contractor"
	case EmploymentInternship:
		return "Intern"
	default:
		return "Employee"
	}
}

// remunerationClause returns the type-specific remuneration paragraph(s).
func remunerationClause(in ContractTermsInput) string {
	switch in.EmploymentType {
	case EmploymentDirector:
		return "<p>Remuneration for the Director is flexible and may comprise any combination of the following, as determined by the Board and/or the shareholders in accordance with the <b>Companies Act, 2015</b>:</p>" +
			"<ul>" +
			"<li>Directors' fees for service on the Board, as approved by ordinary resolution;</li>" +
			"<li>A salary or management fee where the Director also holds an executive/management role; and/or</li>" +
			"<li>A share of profits (dividends) declared out of distributable profits after Corporate Income Tax, where the Director is also a shareholder.</li>" +
			"</ul>" +
			"<p>The mix and amount of remuneration may be varied by the Company from time to time in accordance with applicable law and the Company's constitution.</p>"
	case EmploymentShareholder:
		return "<p>The Shareholder's economic entitlement arises from share ownership rather than employment. The Shareholder is entitled to receive a share of profits (dividends) as and when declared by the Company out of distributable profits remaining after payment of <b>Corporate Income Tax</b>, in proportion to shareholding and in accordance with the <b>Companies Act, 2015</b> and the Company's constitution. No salary or wage is payable by reason of shareholding alone.</p>"
	case EmploymentDirectorShareholder:
		return "<p>As both a Director and a Shareholder, remuneration is flexible and may comprise any combination of the following in accordance with the <b>Companies Act, 2015</b>:</p>" +
			"<ul>" +
			"<li>Directors' fees for service on the Board, as approved by ordinary resolution;</li>" +
			"<li>A salary or management fee for any executive/management role; and</li>" +
			"<li>A share of profits (dividends) declared out of distributable profits after <b>Corporate Income Tax</b>, in proportion to shareholding.</li>" +
			"</ul>" +
			"<p>The specific mix and amounts are determined by the Board and/or shareholders and may be varied from time to time in accordance with applicable law.</p>"
	case EmploymentContractor:
		return "<p>The Contractor shall be paid the agreed contract fee for services rendered, against invoice and subject to any applicable withholding tax. The Contractor is engaged as an independent contractor, is responsible for their own statutory obligations, and is not entitled to employee benefits.</p>"
	case EmploymentCasual:
		return "<p>The Casual Worker shall be paid at the agreed daily rate for each day actually worked, payable in accordance with the <b>Employment Act, 2007</b>. No work, no pay applies, and engagement is on a day-to-day basis.</p>"
	case EmploymentInternship:
		return "<p>The Intern shall be paid the agreed monthly stipend for the duration of the internship. The internship is primarily for training and experience and does not constitute an offer of permanent employment.</p>"
	default: // permanent
		return "<p>The Employee shall be paid a monthly salary, payable monthly in arrears by the last day of each month, subject to lawful statutory deductions (PAYE, SHIF, NSSF and any others required by law). The salary shall be reviewed from time to time at the Company's discretion.</p>"
	}
}

// terminationClause returns the type-specific termination/exit paragraph(s).
func terminationClause(in ContractTermsInput) string {
	switch in.EmploymentType {
	case EmploymentDirector:
		return "<p>The Director's office may be vacated in accordance with the <b>Companies Act, 2015</b>, including removal by <b>ordinary resolution of the shareholders under section 139</b>, resignation, or as otherwise provided in the Company's constitution. This is an office of the company and is not governed by employment notice provisions, save in respect of any separate executive/management role.</p>"
	case EmploymentShareholder:
		return "<p>The Shareholder's relationship with the Company ends only through <b>transfer or disposal of shares</b> in accordance with the <b>Companies Act, 2015</b>, the Company's constitution and any shareholders' agreement (including any pre-emption rights). Shareholding is not terminated by employment notice.</p>"
	case EmploymentDirectorShareholder:
		return "<p>Exit is governed by the <b>Companies Act, 2015</b>: the office of Director may be vacated by removal by <b>ordinary resolution under section 139</b>, resignation or per the Company's constitution; and the shareholding ends only through <b>transfer or disposal of shares</b> subject to the constitution and any shareholders' agreement. Employment notice provisions do not apply, save in respect of any separate executive/management role.</p>"
	case EmploymentContractor:
		return "<p>Either party may terminate this engagement by giving the notice period agreed in the contract (or, if none, thirty (30) days' written notice). The Company may terminate immediately for material breach. On termination the Contractor shall be paid for services properly rendered up to the termination date.</p>"
	case EmploymentCasual:
		return "<p>Engagement is on a day-to-day basis and either party may end it at the close of any working day, subject to the <b>Employment Act, 2007</b>. Continuous casual engagement may convert to a term contract where required by law.</p>"
	case EmploymentInternship:
		return "<p>The internship ends automatically on expiry of the agreed internship period. Either party may end it earlier on two (2) weeks' written notice.</p>"
	default: // permanent
		return "<p>Either party may terminate this employment by giving the notice required under the <b>Employment Act, 2007</b> (or the longer period agreed in writing). The Company may summarily dismiss for gross misconduct in accordance with the Act. On termination the Employee is entitled to all accrued statutory dues.</p>"
	}
}

func addressClause(addr string) string {
	if strings.TrimSpace(addr) == "" {
		return ""
	}
	return " at " + esc(addr)
}

// TenantSlug exposes the tenant slug (branding key) for callers that render tenant-branded
// contracts. Blank on lookup failure.
func (s *Service) TenantSlug(ctx context.Context, tenantID uuid.UUID) string {
	return s.tenantSlug(ctx, tenantID)
}

// ---- Contract terms persistence (tenant-scoped, reuses the Contract ent repo) ----

// EmployeeContract returns the employee's most recent contract row (ent.IsNotFound when none).
func (s *Service) EmployeeContract(ctx context.Context, tenantID, employeeID uuid.UUID) (*ent.Contract, error) {
	return s.orm.Contract.Query().
		Where(contract.TenantID(tenantID), contract.EmployeeID(employeeID)).
		Order(ent.Desc(contract.FieldCreatedAt)).
		First(ctx)
}

// StoredContractTerms returns the saved terms_html for the employee's contract, or "" if there is
// no contract or no stored terms.
func (s *Service) StoredContractTerms(ctx context.Context, tenantID, employeeID uuid.UUID) (string, error) {
	c, err := s.EmployeeContract(ctx, tenantID, employeeID)
	if ent.IsNotFound(err) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return c.TermsHTML, nil
}

// SaveContractTerms upserts the edited HTML onto the employee's contract, creating the Contract
// row if the employee has none. Returns the affected contract.
func (s *Service) SaveContractTerms(ctx context.Context, tenantID, employeeID uuid.UUID, termsHTML string) (*ent.Contract, error) {
	if err := s.ownsEmployee(ctx, tenantID, employeeID); err != nil {
		return nil, err
	}
	c, err := s.EmployeeContract(ctx, tenantID, employeeID)
	if ent.IsNotFound(err) {
		return s.orm.Contract.Create().
			SetTenantID(tenantID).
			SetEmployeeID(employeeID).
			SetTermsHTML(termsHTML).
			Save(ctx)
	}
	if err != nil {
		return nil, err
	}
	return c.Update().SetTermsHTML(termsHTML).Save(ctx)
}

// ---- Branded PDF rendering (reuses the go-pdf/fpdf engine) ----

// RenderContractPDF renders the given HTML terms body into a branded A4 PDF: company letterhead
// (logo + name + address + KRA PIN), the document title, the HTML body, and Employer/Employee
// signature lines. Returns the PDF bytes.
func RenderContractPDF(in ContractTermsInput, termsHTML string) ([]byte, error) {
	pdf := fpdf.New("P", "mm", "A4", "")
	const margin = 18.0
	pdf.SetMargins(margin, 16, margin)
	pdf.SetAutoPageBreak(true, 18)
	pdf.SetTitle("Employment Terms & Contract", true)
	pdf.AddPage()
	pageW, pageH := pdf.GetPageSize()
	tr := pdf.UnicodeTranslatorFromDescriptor("")
	pr, pg, pb := hexToRGB(in.PrimaryColor)

	// Letterhead: logo (left), company block (right).
	if logo, logoType := fetchLogoBytes(in.LogoURL); len(logo) > 0 {
		if info := pdf.RegisterImageOptionsReader("logo", fpdf.ImageOptions{ImageType: logoType}, bytes.NewReader(logo)); info != nil && info.Height() > 0 {
			logoH := 18.0
			logoW := logoH * info.Width() / info.Height()
			pdf.ImageOptions("logo", margin, 12, logoW, logoH, false, fpdf.ImageOptions{ImageType: logoType}, 0, "")
		}
	}
	pdf.SetY(12)
	pdf.SetFont("Helvetica", "B", 16)
	pdf.SetTextColor(pr, pg, pb)
	pdf.CellFormat(0, 8, tr(in.companyName()), "", 2, "R", false, 0, "")
	pdf.SetFont("Helvetica", "", 8.5)
	pdf.SetTextColor(90, 90, 90)
	if in.CompanyAddress != "" {
		pdf.CellFormat(0, 4.4, tr(in.CompanyAddress), "", 2, "R", false, 0, "")
	}
	if in.CompanyKraPin != "" {
		pdf.CellFormat(0, 4.4, tr("KRA PIN: "+in.CompanyKraPin), "", 2, "R", false, 0, "")
	}

	// Divider under the letterhead.
	y := pdf.GetY() + 3
	if y < 34 {
		y = 34
	}
	pdf.SetDrawColor(pr, pg, pb)
	pdf.SetLineWidth(0.6)
	pdf.Line(margin, y, pageW-margin, y)

	// Document title.
	pdf.SetY(y + 6)
	pdf.SetFont("Helvetica", "B", 14)
	pdf.SetTextColor(30, 30, 30)
	pdf.CellFormat(0, 8, "EMPLOYMENT TERMS & CONTRACT", "", 1, "C", false, 0, "")
	pdf.Ln(3)

	// HTML body.
	renderHTMLBody(pdf, termsHTML, pr, pg, pb, tr)

	// Signature lines (Employer / Employee), on a fresh page if we are near the bottom.
	if pdf.GetY() > pageH-50 {
		pdf.AddPage()
	} else {
		pdf.Ln(16)
	}
	drawSignatureLines(pdf, in, margin, pageW, tr)

	var buf bytes.Buffer
	if err := pdf.Output(&buf); err != nil {
		return nil, fmt.Errorf("employees: contract pdf output: %w", err)
	}
	return buf.Bytes(), nil
}

// renderHTMLBody writes a basic-HTML body into the PDF. It reuses fpdf.HTMLBasicTokenize and
// handles the block tags this module emits.
//
// NOTE: fpdf's built-in HTMLBasic writer only supports <b>/<i>/<u>/<br>/<a>. To render the
// semantic body (<h3>/<p>/<ul>/<li>) we tokenize and drive fpdf directly. Any tag not listed
// below (e.g. tables, images, headings other than h3) degrades to plain flowed text — its inner
// text is still printed, only without special styling.
func renderHTMLBody(pdf *fpdf.Fpdf, htmlStr string, pr, pg, pb int, tr func(string) string) {
	const lh = 5.0
	size := 10.0
	bold, italic := 0, 0
	atLineStart := true

	apply := func() {
		style := ""
		if bold > 0 {
			style += "B"
		}
		if italic > 0 {
			style += "I"
		}
		pdf.SetFont("Helvetica", style, size)
	}
	apply()
	pdf.SetTextColor(25, 25, 25)

	for _, el := range fpdf.HTMLBasicTokenize(htmlStr) {
		switch el.Cat {
		case 'T':
			txt := collapseWS(html.UnescapeString(el.Str))
			if atLineStart {
				txt = strings.TrimLeft(txt, " ")
			}
			if txt == "" {
				continue
			}
			pdf.Write(lh, tr(txt))
			atLineStart = false
		case 'O':
			switch el.Str {
			case "h3":
				pdf.Ln(lh * 1.6)
				size = 11.5
				bold++
				apply()
				pdf.SetTextColor(pr, pg, pb)
				atLineStart = true
			case "ul":
				pdf.Ln(lh * 0.4)
				atLineStart = true
			case "li":
				pdf.Ln(lh)
				apply()
				pdf.Write(lh, tr("  •  "))
				atLineStart = false
			case "b", "strong":
				bold++
				apply()
			case "i", "em":
				italic++
				apply()
			case "br":
				pdf.Ln(lh)
				atLineStart = true
			}
		case 'C':
			switch el.Str {
			case "h3":
				bold--
				size = 10.0
				apply()
				pdf.SetTextColor(25, 25, 25)
				pdf.Ln(lh)
				atLineStart = true
			case "p":
				pdf.Ln(lh * 1.5)
				atLineStart = true
			case "ul":
				pdf.Ln(lh * 0.6)
				atLineStart = true
			case "b", "strong":
				bold--
				apply()
			case "i", "em":
				italic--
				apply()
			}
		}
	}
}

// drawSignatureLines draws the Employer (left) and Employee (right) signature blocks.
func drawSignatureLines(pdf *fpdf.Fpdf, in ContractTermsInput, margin, pageW float64, tr func(string) string) {
	colW := (pageW - 2*margin - 12) / 2
	rightX := margin + colW + 12
	y := pdf.GetY()

	line := func(x float64) {
		pdf.SetDrawColor(120, 120, 120)
		pdf.SetLineWidth(0.3)
		pdf.Line(x, y+8, x+colW, y+8)
	}
	line(margin)
	line(rightX)

	label := func(x float64, l, v string) {
		pdf.SetXY(x, y+9)
		pdf.SetFont("Helvetica", "B", 9)
		pdf.SetTextColor(40, 40, 40)
		pdf.CellFormat(colW, 5, tr(l), "", 2, "L", false, 0, "")
		pdf.SetFont("Helvetica", "", 8.5)
		pdf.SetTextColor(90, 90, 90)
		if v != "" {
			pdf.CellFormat(colW, 4.4, tr(v), "", 2, "L", false, 0, "")
		}
		pdf.CellFormat(colW, 4.4, tr("Signature / Date"), "", 2, "L", false, 0, "")
	}
	label(margin, "For and on behalf of the Employer", in.companyName())
	label(rightX, "The "+appointee(in.EmploymentType), in.employeeName())
}

// ---- small helpers (self-contained; no new dependencies) ----

func firstNonBlank(a, b string) string {
	if strings.TrimSpace(a) != "" {
		return a
	}
	return b
}

// esc HTML-escapes dynamic text before embedding it into the generated terms HTML.
func esc(s string) string { return html.EscapeString(s) }

// collapseWS collapses runs of whitespace to a single space.
func collapseWS(s string) string { return strings.Join(strings.Fields(s), " ") }

// hexToRGB parses a "#rrggbb" hex color, returning a default indigo (99,102,241) on any failure.
func hexToRGB(hex string) (int, int, int) {
	hex = strings.TrimPrefix(strings.TrimSpace(hex), "#")
	if len(hex) == 3 {
		hex = string([]byte{hex[0], hex[0], hex[1], hex[1], hex[2], hex[2]})
	}
	if len(hex) != 6 {
		return 99, 102, 241
	}
	var r, g, b int
	if _, err := fmt.Sscanf(hex, "%02x%02x%02x", &r, &g, &b); err != nil {
		return 99, 102, 241
	}
	return r, g, b
}

// fetchLogoBytes downloads the tenant logo and reports its fpdf image type ("PNG"/"JPG"/"GIF").
// Returns nil on any failure (graceful degradation — the PDF renders without a logo). Mirrors the
// docs module's own logo fetch.
func fetchLogoBytes(logoURL string) ([]byte, string) {
	if strings.TrimSpace(logoURL) == "" {
		return nil, ""
	}
	resp, err := http.Get(logoURL) //nolint:gosec // URL from trusted auth-api branding
	if err != nil {
		return nil, ""
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, ""
	}
	b, err := io.ReadAll(resp.Body)
	if err != nil || len(b) == 0 {
		return nil, ""
	}
	return b, imgType(b)
}

// imgType detects the fpdf image type from magic bytes.
func imgType(b []byte) string {
	switch {
	case len(b) >= 8 && b[0] == 0x89 && b[1] == 'P' && b[2] == 'N' && b[3] == 'G':
		return "PNG"
	case len(b) >= 3 && b[0] == 0xFF && b[1] == 0xD8 && b[2] == 0xFF:
		return "JPG"
	case len(b) >= 3 && b[0] == 'G' && b[1] == 'I' && b[2] == 'F':
		return "GIF"
	default:
		return "PNG"
	}
}
