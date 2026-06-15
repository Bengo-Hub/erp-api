package docs

import (
	"fmt"

	"github.com/Bengo-Hub/erp-api/internal/modules/docs/builders"
	"github.com/xuri/excelize/v2"
)

// GenerateXLSX returns an Excel (.xlsx) workbook for the given Document. Payroll
// reports render their tabular schedule; payslips render the earnings/deductions
// breakdown; other types fall back to the generic line table.
func GenerateXLSX(doc *Document) ([]byte, error) {
	f := excelize.NewFile()
	defer f.Close()

	sheet := "Document"
	f.SetSheetName("Sheet1", sheet)

	titleStyle, _ := f.NewStyle(&excelize.Style{
		Font:      &excelize.Font{Bold: true, Size: 14, Color: builders.HexSlate800},
		Alignment: &excelize.Alignment{Horizontal: "left"},
	})
	headerStyle, _ := f.NewStyle(&excelize.Style{
		Font:      &excelize.Font{Bold: true, Color: builders.HexWhite, Size: 9},
		Fill:      excelize.Fill{Type: "pattern", Pattern: 1, Color: []string{builders.HexIndigo}},
		Alignment: &excelize.Alignment{Horizontal: "center"},
	})
	labelStyle, _ := f.NewStyle(&excelize.Style{
		Font: &excelize.Font{Bold: true, Size: 9, Color: builders.HexSlate500},
	})
	valueStyle, _ := f.NewStyle(&excelize.Style{
		Font: &excelize.Font{Size: 9},
	})
	totalStyle, _ := f.NewStyle(&excelize.Style{
		Font:      &excelize.Font{Bold: true, Size: 10, Color: builders.HexSlate800},
		Alignment: &excelize.Alignment{Horizontal: "right"},
	})
	altRowStyle, _ := f.NewStyle(&excelize.Style{
		Font: &excelize.Font{Size: 9},
		Fill: excelize.Fill{Type: "pattern", Pattern: 1, Color: []string{builders.HexSlate100}},
	})

	row := 1
	switch doc.Type {
	case DocTypePayrollReport:
		row = writeReportXLSX(f, sheet, doc, row, titleStyle, headerStyle, valueStyle, altRowStyle, totalStyle)
	case DocTypePayslip:
		row = writePayslipXLSX(f, sheet, doc, row, titleStyle, headerStyle, labelStyle, valueStyle, totalStyle)
	default:
		row = writeGenericXLSX(f, sheet, doc, row, titleStyle, headerStyle, labelStyle, valueStyle, altRowStyle, totalStyle)
	}
	_ = row

	for c := 1; c <= 8; c++ {
		colName, _ := excelize.ColumnNumberToName(c)
		f.SetColWidth(sheet, colName, colName, 18)
	}
	f.SetColWidth(sheet, "A", "A", 30)

	buf, err := f.WriteToBuffer()
	if err != nil {
		return nil, fmt.Errorf("xlsx write: %w", err)
	}
	return buf.Bytes(), nil
}

func writeReportXLSX(f *excelize.File, sheet string, doc *Document, row, titleStyle, headerStyle, valueStyle, altRowStyle, totalStyle int) int {
	f.SetCellValue(sheet, cell(1, row), ifEmpty(doc.ReportTitle, docTypeTitle(doc.Type)))
	f.SetCellStyle(sheet, cell(1, row), cell(1, row), titleStyle)
	row += 2

	for c, h := range doc.ReportColumns {
		f.SetCellValue(sheet, cell(c+1, row), h)
		f.SetCellStyle(sheet, cell(c+1, row), cell(c+1, row), headerStyle)
	}
	row++

	for i, r := range doc.ReportRows {
		s := valueStyle
		if i%2 == 1 {
			s = altRowStyle
		}
		for c, v := range r {
			ref := cell(c+1, row)
			f.SetCellValue(sheet, ref, v)
			f.SetCellStyle(sheet, ref, ref, s)
		}
		row++
	}
	for c, v := range doc.ReportTotals {
		ref := cell(c+1, row)
		f.SetCellValue(sheet, ref, v)
		f.SetCellStyle(sheet, ref, ref, totalStyle)
	}
	if len(doc.ReportTotals) > 0 {
		row++
	}
	return row
}

func writePayslipXLSX(f *excelize.File, sheet string, doc *Document, row, titleStyle, headerStyle, labelStyle, valueStyle, totalStyle int) int {
	f.SetCellValue(sheet, cell(1, row), "Payslip — "+doc.CustomerName)
	f.SetCellStyle(sheet, cell(1, row), cell(1, row), titleStyle)
	row += 2

	meta := [][]string{
		{"Payslip No.", doc.DocNumber},
		{"Staff No.", doc.EmployeeNumber},
		{"Period", doc.PeriodLabel},
		{"Currency", doc.Currency},
	}
	for _, m := range meta {
		f.SetCellValue(sheet, cell(1, row), m[0])
		f.SetCellStyle(sheet, cell(1, row), cell(1, row), labelStyle)
		f.SetCellValue(sheet, cell(2, row), m[1])
		f.SetCellStyle(sheet, cell(2, row), cell(2, row), valueStyle)
		row++
	}
	row++

	f.SetCellValue(sheet, cell(1, row), "Earnings")
	f.SetCellValue(sheet, cell(2, row), "Amount")
	f.SetCellStyle(sheet, cell(1, row), cell(2, row), headerStyle)
	row++
	for _, e := range doc.Earnings {
		f.SetCellValue(sheet, cell(1, row), e.Label)
		f.SetCellValue(sheet, cell(2, row), e.Amount.InexactFloat64())
		f.SetCellStyle(sheet, cell(1, row), cell(2, row), valueStyle)
		row++
	}
	row++

	f.SetCellValue(sheet, cell(1, row), "Deductions")
	f.SetCellValue(sheet, cell(2, row), "Amount")
	f.SetCellStyle(sheet, cell(1, row), cell(2, row), headerStyle)
	row++
	for _, d := range doc.Deductions {
		f.SetCellValue(sheet, cell(1, row), d.Label)
		f.SetCellValue(sheet, cell(2, row), d.Amount.InexactFloat64())
		f.SetCellStyle(sheet, cell(1, row), cell(2, row), valueStyle)
		row++
	}
	row++

	f.SetCellValue(sheet, cell(1, row), "Net Pay")
	f.SetCellStyle(sheet, cell(1, row), cell(1, row), labelStyle)
	f.SetCellValue(sheet, cell(2, row), doc.TotalAmount.InexactFloat64())
	f.SetCellStyle(sheet, cell(2, row), cell(2, row), totalStyle)
	row++
	return row
}

func writeGenericXLSX(f *excelize.File, sheet string, doc *Document, row, titleStyle, headerStyle, labelStyle, valueStyle, altRowStyle, totalStyle int) int {
	f.SetCellValue(sheet, cell(1, row), docTypeTitle(doc.Type))
	f.SetCellStyle(sheet, cell(1, row), cell(1, row), titleStyle)
	row += 2

	for c, h := range LineHeaders {
		f.SetCellValue(sheet, cell(c+1, row), h)
		f.SetCellStyle(sheet, cell(c+1, row), cell(c+1, row), headerStyle)
	}
	row++
	for i, l := range doc.Lines {
		s := valueStyle
		if i%2 == 1 {
			s = altRowStyle
		}
		vals := []interface{}{
			i + 1, l.Description, l.Quantity.InexactFloat64(), l.UnitPrice.InexactFloat64(),
			l.TaxRate.InexactFloat64(), l.TaxAmount.InexactFloat64(),
			l.DiscountAmount.InexactFloat64(), l.LineTotal.InexactFloat64(),
		}
		for c, v := range vals {
			ref := cell(c+1, row)
			f.SetCellValue(sheet, ref, v)
			f.SetCellStyle(sheet, ref, ref, s)
		}
		row++
	}
	row++
	f.SetCellValue(sheet, cell(7, row), "Total")
	f.SetCellStyle(sheet, cell(7, row), cell(7, row), labelStyle)
	f.SetCellValue(sheet, cell(8, row), doc.TotalAmount.InexactFloat64())
	f.SetCellStyle(sheet, cell(8, row), cell(8, row), totalStyle)
	row++
	return row
}

// cell returns an Excel cell reference like "A1" for column c (1-indexed), row r (1-indexed).
func cell(c, r int) string {
	name, _ := excelize.ColumnNumberToName(c)
	return fmt.Sprintf("%s%d", name, r)
}
