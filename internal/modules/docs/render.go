package docs

import (
	"bytes"
	"fmt"
	"strings"

	"github.com/go-pdf/fpdf"
)

// renderPDF builds a premium, tenant-branded A4 PDF for the given document. logo
// holds the (already-fetched) tenant logo bytes; logoType is the fpdf image type
// ("PNG"/"JPG"/"GIF"). Both may be empty — the logo is then omitted.
func renderPDF(d *Document, logo []byte, logoType string) ([]byte, error) {
	pdf := fpdf.New("P", "mm", "A4", "")
	pdf.SetMargins(margin, 12, margin)
	pdf.SetAutoPageBreak(true, 14)
	pdf.AddPage()

	p := newPainter(pdf, newPalette(d.TenantPrimaryColor))
	prof := profileFor(d.Type)

	y := p.drawHeader(d, logo, logoType)
	y = p.drawMetaAndCompany(d, y)
	y = p.drawParties(d, y+6.0)
	if prof.showAmountBanner {
		y = p.drawBanner(d, y+6.0)
	}
	if prof.acknowledgement != "" {
		y = p.drawAcknowledgement(prof.acknowledgement, y+6.0)
	}

	switch {
	case prof.payslipBody:
		y = p.drawPayslipBody(d, y+6.0)
	case prof.reportBody:
		y = p.drawReportTable(d, y+6.0)
	default:
		y = p.drawItems(d, y+6.0)
		if prof.showTotals {
			y = p.drawTotals(d, y+4.0)
		}
	}

	y = p.drawLowerBlocks(d, y+6.0)

	// Pin signatures + footer to the bottom of the page so the footer always sits at
	// the foot of the document regardless of content length.
	const (
		bottomMargin = 12.0
		footerBlockH = 12.0
		sigGap       = 16.0
	)
	pinnedSigY := pageH - bottomMargin - footerBlockH - sigGap
	sigY := y + 14.0
	if sigY < pinnedSigY {
		sigY = pinnedSigY
	}
	p.pdf.SetAutoPageBreak(false, 0)
	p.drawSignatures(d, sigY)
	p.drawFooter(d, sigY+sigGap)

	var buf bytes.Buffer
	if err := pdf.Output(&buf); err != nil {
		return nil, fmt.Errorf("pdf output: %w", err)
	}
	return buf.Bytes(), nil
}

// drawHeader renders the logo (left), document title + subtitle (right) and the
// gradient rule beneath. Returns the y just below the rule.
func (p *painter) drawHeader(d *Document, logo []byte, logoType string) float64 {
	topY := 11.0
	logoH := 22.0
	if len(logo) > 0 {
		if logoType == "" {
			logoType = imgType(logo)
		}
		info := p.pdf.RegisterImageOptionsReader("logo",
			fpdf.ImageOptions{ImageType: logoType}, bytes.NewReader(logo))
		if info != nil && info.Height() > 0 {
			logoW := logoH * info.Width() / info.Height()
			p.pdf.ImageOptions("logo", leftX, topY, logoW, logoH, false,
				fpdf.ImageOptions{ImageType: logoType}, 0, "")
		}
	}

	p.textR(rightX, topY+0.5, strings.ToUpper(headerTitle(d.Type)), "B", 27, p.pal.navy)
	p.textR(rightX, topY+11.0, docTypeSubtitle(d.Type), "", 7.5, p.pal.blue)

	ruleY := topY + logoH + 2.0
	p.gradient(leftX, ruleY, contentW, 1.4, 0.7, p.pal.sky, p.pal.navy)
	return ruleY
}

// drawMetaAndCompany renders the company block (left) and the meta key/value box
// (right). Returns the y below whichever column is taller.
func (p *painter) drawMetaAndCompany(d *Document, ruleY float64) float64 {
	y := ruleY + 6.0

	const companyW = 117.0 - leftX - 8.0
	p.text(leftX, y, ifEmpty(d.TenantName, "—"), "B", 15, p.pal.navy)
	ly := y + 6.4
	if d.Tagline != "" {
		p.text(leftX, ly, d.Tagline, "I", 9, p.pal.blue)
		ly += 4.6
	} else {
		ly = y + 10.8
	}
	if addr := companyAddressText(d); addr != "" {
		ly = p.multiCell(leftX, ly, companyW, 4.4, addr, "", 9, p.pal.grey) + 0.8
	}
	if d.TaxPIN != "" {
		p.text(leftX, ly, "Tax PIN: "+d.TaxPIN, "B", 8.5, p.pal.navy)
		ly += 4.2
	}

	rows := metaRows(d)
	mbX := 117.0
	mbW := rightX - mbX
	keyW := mbW * 0.46
	valW := mbW - keyW - 5.0
	const (
		rowMinH = 6.4
		valLnH  = 3.4
	)
	ry := y
	for i, r := range rows {
		p.pdf.SetFont("Helvetica", "B", 8)
		valLines := p.splitText(p.tr(r[1]), valW)
		if len(valLines) == 0 {
			valLines = []string{""}
		}
		rh := rowMinH
		if h := float64(len(valLines))*valLnH + 2.9; h > rh {
			rh = h
		}
		p.setFill(p.pal.lightBlue)
		p.pdf.Rect(mbX, ry, keyW, rh, "F")
		if i > 0 {
			p.hline(mbX, ry, mbX+mbW)
		}
		p.text(mbX+2.5, ry+2.1, strings.ToUpper(r[0]), "B", 7.5, p.pal.blue)
		vy := ry + 2.1
		for _, ln := range valLines {
			p.text(mbX+keyW+2.5, vy, ln, "B", 8.0, p.pal.navy)
			vy += valLnH
		}
		ry += rh
	}
	mbH := ry - y
	p.box(mbX, y, mbW, mbH)

	return maxF(y+mbH, ly)
}

// drawParties renders the two side-by-side party boxes. Returns the y below them.
func (p *painter) drawParties(d *Document, py float64) float64 {
	boxH := 34.0
	bw := (contentW - 6.0) / 2
	bx2 := leftX + bw + 6.0

	fromLabel, toLabel := partyLabels(d.Type)

	// Left box: the subject (employee on a payslip) — name, contact + tax PIN.
	p.box(leftX, py, bw, boxH)
	p.text(leftX+3, py+3.0, fromLabel, "B", 8, p.pal.blue)
	endY := p.multiCell(leftX+3, py+6.5, bw-6, 4.0, ifEmpty(d.CustomerName, "—"), "B", 10.5, p.pal.navy)
	cy := endY + 1.0
	for _, ln := range customerAddressLines(d) {
		p.text(leftX+3, cy, ln, "", 9, p.pal.grey)
		cy += 4.0
	}
	for _, ln := range partyContactLines(d) {
		p.text(leftX+3, cy, ln, "", 9, p.pal.grey)
		cy += 4.0
	}

	// Right box: issuer (the tenant).
	p.box(bx2, py, bw, boxH)
	p.text(bx2+3, py+3.0, toLabel, "B", 8, p.pal.blue)
	ry := p.multiCell(bx2+3, py+6.5, bw-6, 4.0, ifEmpty(d.TenantName, "—"), "B", 10.5, p.pal.navy) + 1.0
	for _, ln := range issuerContactLines(d) {
		p.text(bx2+3, ry, ln, "", 9, p.pal.grey)
		ry += 4.0
	}

	return py + boxH
}

// drawAcknowledgement renders a bold lead line above the body.
func (p *painter) drawAcknowledgement(text string, y float64) float64 {
	p.text(leftX, y+2.0, text, "B", 9.5, p.pal.navy)
	return y + 4.0
}

// drawBanner renders the gradient amount banner with the status badge.
func (p *painter) drawBanner(d *Document, by float64) float64 {
	banH := 18.0
	p.gradient(leftX, by, contentW, banH, 2.0, p.pal.sky, p.pal.navy)
	p.text(leftX+8, by+4.5, strings.ToUpper(amountLabel(d)), "", 9, p.pal.bannerSub)
	p.text(leftX+8, by+8.5, money(d.Currency, d.TotalAmount), "B", 24, p.pal.white)

	badge := badgeText(d)
	if badge != "" {
		badgeW := 34.0
		bgx := rightX - 8 - badgeW
		bgy := by + 4.0
		p.pdf.SetDrawColor(255, 255, 255)
		p.pdf.SetLineWidth(0.8)
		p.pdf.RoundedRect(bgx, bgy, badgeW, 10.0, 1.4, "1234", "D")
		p.pdf.SetFont("Helvetica", "B", 13)
		p.setText(p.pal.white)
		p.pdf.SetXY(bgx, bgy+1.2)
		p.pdf.CellFormat(badgeW, 8.0, p.tr(badge), "", 0, "C", false, 0, "")
	}
	return by + banH
}

func maxF(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}
