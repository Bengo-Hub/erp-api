package docs

import (
	"bytes"
	"encoding/csv"
	"fmt"
)

// GenerateCSV writes the document as a UTF-8 CSV to a buffer. The layout depends on
// the document type: payroll reports emit their tabular schedule; payslips emit the
// earnings/deductions breakdown; other types fall back to the generic line table.
func GenerateCSV(doc *Document) ([]byte, error) {
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)

	switch doc.Type {
	case DocTypePayrollReport:
		if err := writeReportCSV(w, doc); err != nil {
			return nil, err
		}
	case DocTypePayslip:
		if err := writePayslipCSV(w, doc); err != nil {
			return nil, err
		}
	default:
		if err := writeGenericCSV(w, doc); err != nil {
			return nil, err
		}
	}

	w.Flush()
	if err := w.Error(); err != nil {
		return nil, fmt.Errorf("csv flush: %w", err)
	}
	return buf.Bytes(), nil
}

func writeReportCSV(w *csv.Writer, doc *Document) error {
	if doc.ReportTitle != "" {
		if err := w.Write([]string{doc.ReportTitle}); err != nil {
			return fmt.Errorf("csv write title: %w", err)
		}
	}
	if len(doc.ReportColumns) > 0 {
		if err := w.Write(doc.ReportColumns); err != nil {
			return fmt.Errorf("csv write report header: %w", err)
		}
	}
	for _, row := range doc.ReportRows {
		if err := w.Write(row); err != nil {
			return fmt.Errorf("csv write report row: %w", err)
		}
	}
	if len(doc.ReportTotals) > 0 {
		if err := w.Write(doc.ReportTotals); err != nil {
			return fmt.Errorf("csv write report totals: %w", err)
		}
	}
	return nil
}

func writePayslipCSV(w *csv.Writer, doc *Document) error {
	rows := [][]string{
		{"Payslip", doc.DocNumber},
		{"Employee", doc.CustomerName},
		{"Staff No.", doc.EmployeeNumber},
		{"Period", doc.PeriodLabel},
		{"Currency", doc.Currency},
		{},
		{"Earnings", "Amount"},
	}
	for _, e := range doc.Earnings {
		rows = append(rows, []string{e.Label, e.Amount.StringFixed(2)})
	}
	rows = append(rows, []string{}, []string{"Deductions", "Amount"})
	for _, dd := range doc.Deductions {
		rows = append(rows, []string{dd.Label, dd.Amount.StringFixed(2)})
	}
	rows = append(rows, []string{}, []string{"Net Pay", doc.TotalAmount.StringFixed(2)})
	if err := w.WriteAll(rows); err != nil {
		return fmt.Errorf("csv write payslip: %w", err)
	}
	return nil
}

func writeGenericCSV(w *csv.Writer, doc *Document) error {
	if err := w.WriteAll([][]string{
		{"Document Type", string(doc.Type)},
		{"Number", doc.DocNumber},
		{"From", doc.TenantName},
		{"To", doc.CustomerName},
		{"Currency", doc.Currency},
		{},
		{"Total", doc.TotalAmount.StringFixed(2)},
		{},
	}); err != nil {
		return fmt.Errorf("csv write header: %w", err)
	}
	if err := w.Write(LineHeaders); err != nil {
		return fmt.Errorf("csv write line headers: %w", err)
	}
	for _, row := range doc.ToRows() {
		if err := w.Write(row); err != nil {
			return fmt.Errorf("csv write row: %w", err)
		}
	}
	return nil
}
