package docs

import (
	"fmt"

	"github.com/Bengo-Hub/erp-api/internal/modules/docs/builders"
	"github.com/shopspring/decimal"
)

// drawPayslipBody renders the payslip earnings-vs-deductions two-column breakdown
// followed by the "Net Pay" grand total and the amount-in-words band. Each column is
// a self-contained card with a header bar, one row per AmountRow and a column subtotal.
// Returns the y below the totals band.
func (p *painter) drawPayslipBody(d *Document, top float64) float64 {
	colW := (contentW - 6.0) / 2
	rightColX := leftX + colW + 6.0

	cur := currencyCode(d.Currency)
	leftBottom := p.drawAmountColumn(leftX, top, colW, "EARNINGS", cur, d.Earnings, p.earningsTotal(d))
	rightBottom := p.drawAmountColumn(rightColX, top, colW, "DEDUCTIONS", cur, d.Deductions, p.deductionsTotal(d))

	y := maxF(leftBottom, rightBottom) + 4.0

	// Net Pay grand-total bar (full width).
	gtY := y
	p.gradient(leftX, gtY, contentW, 10.0, 1.4, p.pal.blue, p.pal.navy)
	p.text(leftX+5, gtY+3.6, grandTotalLabel(d), "B", 13, p.pal.white)
	p.textR(rightX-5, gtY+3.6, money(d.Currency, d.TotalAmount), "B", 14, p.pal.white)
	y = gtY + 10.0

	// Amount-in-words band.
	words := builders.AmountInWords(d.Currency, d.TotalAmount)
	const labelW = 30.0
	availW := contentW - labelW - 8.0
	lineH := 3.6
	p.pdf.SetFont("Helvetica", "B", 8)
	nLines := len(p.pdf.SplitText(p.tr(words), availW))
	if nLines < 1 {
		nLines = 1
	}
	bandH := maxF(8.0, float64(nLines)*lineH+4.0)
	wY := y + 5.0
	p.setFill(p.pal.lightBlue)
	p.pdf.RoundedRect(leftX, wY, contentW, bandH, 1.2, "1234", "F")
	p.text(leftX+4, wY+2.6, "Net Pay in Words:", "B", 8, p.pal.muted)
	p.multiCell(leftX+labelW+2, wY+2.0, availW, lineH, words, "B", 8, p.pal.navy)

	return p.drawPersonalInfo(d, wY+bandH+5.0)
}

// drawPersonalInfo renders the wingubox-style "PERSONAL INFO" strip under the breakdown: payment
// mode + bank, statutory numbers (ID / PIN / SHIF / NSSF), department/region and the created date.
// Only non-empty pairs are shown; the block is skipped entirely when there is nothing to render.
func (p *painter) drawPersonalInfo(d *Document, top float64) float64 {
	type kv struct{ k, v string }
	pairs := []kv{{"Payment Mode", d.EmployeePaymentMode}}
	if d.BankDetails != nil {
		pairs = append(pairs, kv{"Bank Name", d.BankDetails.BankName}, kv{"Bank Acc", d.BankDetails.AccountNumber})
	}
	pairs = append(pairs,
		kv{"ID", d.EmployeeNationalID}, kv{"PIN", d.CustomerTaxPin},
		kv{"SHIF", d.EmployeeShif}, kv{"NSSF", d.EmployeeNssf},
		kv{"Department", d.EmployeeDepartment}, kv{"Region", d.EmployeeRegion},
	)
	shown := make([]kv, 0, len(pairs))
	for _, pr := range pairs {
		if pr.v != "" {
			shown = append(shown, pr)
		}
	}
	if len(shown) == 0 {
		return top
	}

	const cols = 2
	colW := contentW / cols
	rowH := 5.2
	rows := (len(shown) + cols - 1) / cols
	headH := 6.0
	boxH := headH + float64(rows)*rowH + 2.0

	p.setFill(p.pal.navy)
	p.pdf.Rect(leftX, top, contentW, headH, "F")
	p.text(leftX+3, top+2.2, "PERSONAL INFO", "B", 8, p.pal.white)
	p.setFill(p.pal.lightBlue)
	p.pdf.Rect(leftX, top+headH, contentW, float64(rows)*rowH+2.0, "F")

	for i, pr := range shown {
		cx := leftX + float64(i%cols)*colW + 3
		ry := top + headH + float64(i/cols)*rowH + 3.0
		p.text(cx, ry, pr.k+":", "B", 7.5, p.pal.muted)
		p.text(cx+26, ry, pr.v, "", 8, p.pal.navy)
	}
	if d.CreatedDate != "" {
		p.text(leftX, top+boxH+2.5, "Created: "+d.CreatedDate, "", 7, p.pal.grey)
		boxH += 4.0
	}
	return top + boxH
}

// drawAmountColumn renders one labelled card (earnings or deductions) with a header
// bar, the rows, and a subtotal row. Returns the y at the bottom of the card.
func (p *painter) drawAmountColumn(x, top, w float64, title, cur string, rows []AmountRow, total decimal.Decimal) float64 {
	headH := 8.0
	rowH := 6.0
	subH := 8.0
	bodyH := float64(len(rows)) * rowH
	cardH := headH + bodyH + subH

	// Header bar.
	p.setFill(p.pal.navy)
	p.pdf.Rect(x, top, w, headH, "F")
	p.text(x+3, top+2.7, title, "B", 8.5, p.pal.white)
	p.textR(x+w-3, top+2.7, "AMOUNT ("+cur+")", "B", 7.5, p.pal.white)

	// Rows.
	ry := top + headH
	for i, r := range rows {
		if i%2 == 1 {
			p.setFill(p.pal.lightBlue)
			p.pdf.Rect(x, ry, w, rowH, "F")
		}
		p.text(x+3, ry+1.6, r.Label, "", 9, p.pal.ink)
		p.textR(x+w-3, ry+1.6, builders.FormatFloat(r.Amount.InexactFloat64()), "", 9, p.pal.ink)
		ry += rowH
	}

	// Subtotal.
	p.setFill(p.pal.lightBlue)
	p.pdf.RoundedRect(x, ry, w, subH, 1.0, "1234", "F")
	p.text(x+3, ry+2.4, "Total", "B", 9, p.pal.grey)
	p.textR(x+w-3, ry+2.4, builders.FormatFloat(total.InexactFloat64()), "B", 9.5, p.pal.navy)

	// Outer border.
	p.box(x, top, w, cardH)
	return top + cardH
}

func (p *painter) earningsTotal(d *Document) decimal.Decimal {
	t := decimal.Zero
	for _, r := range d.Earnings {
		t = t.Add(r.Amount)
	}
	return t
}

func (p *painter) deductionsTotal(d *Document) decimal.Decimal {
	t := decimal.Zero
	for _, r := range d.Deductions {
		t = t.Add(r.Amount)
	}
	return t
}

// drawReportTable renders the payroll-report tabular schedule: a header bar with the
// report's columns, one striped row per ReportRows entry, and a bold totals row.
// Returns the y below the last row.
func (p *painter) drawReportTable(d *Document, ty float64) float64 {
	cols := d.ReportColumns
	if len(cols) == 0 {
		return ty
	}
	n := len(cols)
	colW := contentW / float64(n)

	// Title line above the table.
	if d.ReportTitle != "" {
		p.text(leftX, ty, d.ReportTitle, "B", 11, p.pal.navy)
		ty += 6.0
	}

	// Header bar.
	headH := 8.0
	p.setFill(p.pal.navy)
	p.pdf.Rect(leftX, ty, contentW, headH, "F")
	for i, c := range cols {
		cx := leftX + float64(i)*colW
		if i == 0 {
			p.text(cx+2, ty+2.7, c, "B", 7.5, p.pal.white)
		} else {
			p.textR(cx+colW-2, ty+2.7, c, "B", 7.5, p.pal.white)
		}
	}
	ry := ty + headH

	rowH := 6.0
	for ri, row := range d.ReportRows {
		if ri%2 == 1 {
			p.setFill(p.pal.lightBlue)
			p.pdf.Rect(leftX, ry, contentW, rowH, "F")
		}
		for i := 0; i < n; i++ {
			cx := leftX + float64(i)*colW
			val := ""
			if i < len(row) {
				val = row[i]
			}
			if i == 0 {
				p.text(cx+2, ry+1.7, val, "", 8.2, p.pal.ink)
			} else {
				p.textR(cx+colW-2, ry+1.7, val, "", 8.2, p.pal.ink)
			}
		}
		ry += rowH
		p.hline(leftX, ry, rightX)
	}

	// Totals row.
	if len(d.ReportTotals) > 0 {
		p.setFill(p.pal.lightBlue)
		p.pdf.Rect(leftX, ry, contentW, rowH+1.0, "F")
		for i := 0; i < n; i++ {
			cx := leftX + float64(i)*colW
			val := ""
			if i < len(d.ReportTotals) {
				val = d.ReportTotals[i]
			}
			if i == 0 {
				p.text(cx+2, ry+1.9, ifEmpty(val, "Total"), "B", 8.4, p.pal.navy)
			} else {
				p.textR(cx+colW-2, ry+1.9, val, "B", 8.4, p.pal.navy)
			}
		}
		ry += rowH + 1.0
	}
	return ry
}

// drawItems renders the generic line-item table (kept for the shared base pipeline).
func (p *painter) drawItems(d *Document, ty float64) float64 {
	colNum := 9.0
	colAmt := 30.0
	colTax := 15.0
	colRate := 26.0
	colQty := 16.0
	colDesc := contentW - colNum - colAmt - colTax - colRate - colQty

	xNum := leftX
	xDesc := xNum + colNum
	xQtyR := xDesc + colDesc + colQty
	xRateR := xQtyR + colRate
	xTaxR := xRateR + colTax
	xAmtR := rightX

	p.setFill(p.pal.navy)
	p.pdf.Rect(leftX, ty, contentW, 8.0, "F")
	p.text(xNum+2, ty+2.7, "#", "B", 8, p.pal.white)
	p.text(xDesc+1, ty+2.7, "DESCRIPTION", "B", 8, p.pal.white)
	p.textR(xQtyR-1, ty+2.7, "QTY", "B", 8, p.pal.white)
	p.textR(xRateR-1, ty+2.7, "RATE", "B", 8, p.pal.white)
	p.textR(xTaxR-1, ty+2.7, "TAX%", "B", 8, p.pal.white)
	p.textR(xAmtR-2, ty+2.7, "AMOUNT ("+currencyCode(d.Currency)+")", "B", 8, p.pal.white)

	ry := ty + 8.0
	for i, it := range d.Lines {
		rowTop := ry + 2.5
		endY := p.multiCell(xDesc+1, rowTop, colDesc-2, 4.0, it.Description, "B", 9.3, p.pal.navy)
		p.text(xNum+2, rowTop, fmt.Sprintf("%d", i+1), "", 9.3, p.pal.ink)
		p.textR(xQtyR-1, rowTop, trimDecimal(it.Quantity), "", 9.3, p.pal.ink)
		p.textR(xRateR-1, rowTop, builders.FormatFloat(it.UnitPrice.InexactFloat64()), "", 9.3, p.pal.ink)
		p.textR(xTaxR-1, rowTop, it.TaxRate.StringFixed(0)+"%", "", 9.3, p.pal.muted)
		p.textR(xAmtR-2, rowTop, builders.FormatFloat(it.LineTotal.InexactFloat64()), "B", 9.3, p.pal.ink)
		ry = endY + 2.0
		p.hline(leftX, ry, rightX)
	}
	return ry
}

// drawTotals renders the subtotal/tax stack and the gradient grand total.
func (p *painter) drawTotals(d *Document, top float64) float64 {
	tlW := 92.0
	tlX := rightX - tlW

	y := top
	p.setFill(p.pal.lightBlue)
	p.pdf.RoundedRect(tlX, y, tlW, 7.5, 1.2, "1234", "F")
	p.text(tlX+4, y+2.6, "Subtotal", "", 10, p.pal.grey)
	p.textR(rightX-4, y+2.6, money(d.Currency, d.Subtotal), "B", 10, p.pal.navy)
	y += 8.3

	if !d.TaxAmount.IsZero() {
		p.text(tlX+4, y+1.0, "Tax", "", 10, p.pal.grey)
		p.textR(rightX-4, y+1.0, money(d.Currency, d.TaxAmount), "B", 10, p.pal.navy)
		y += 6.5
	}

	gtY := y + 1.0
	p.gradient(tlX, gtY, tlW, 9.0, 1.4, p.pal.blue, p.pal.navy)
	p.text(tlX+4, gtY+3.2, grandTotalLabel(d), "B", 12, p.pal.white)
	p.textR(rightX-4, gtY+3.2, money(d.Currency, d.TotalAmount), "B", 12.5, p.pal.white)
	return gtY + 9.0
}
