package adapters

import (
	"fmt"
	"strings"

	"github.com/Bengo-Hub/erp-api/internal/modules/docs"
	"github.com/Bengo-Hub/erp-api/internal/modules/reports"
)

// ReportToDocument converts a reports.Report (columns + map rows + totals) into the
// generic Document tabular-schedule model. Cell values are stringified in column order;
// the totals row reuses the report Totals map keyed by the same columns so the footer
// aligns with the table. docNumber/period drive the meta box.
func ReportToDocument(rep *reports.Report, docNumber string, ti TenantInfo) *docs.Document {
	cols := rep.Columns
	headers := make([]string, len(cols))
	for i, c := range cols {
		headers[i] = humanizeColumn(c)
	}

	rows := make([][]string, 0, len(rep.Rows))
	for _, r := range rep.Rows {
		row := make([]string, len(cols))
		for i, c := range cols {
			row[i] = cellString(r[c])
		}
		rows = append(rows, row)
	}

	// Totals row: place "Total" under the first column, then any matching totals values.
	var totals []string
	if len(rep.Totals) > 0 {
		totals = make([]string, len(cols))
		for i, c := range cols {
			if i == 0 {
				totals[i] = "Total"
				continue
			}
			if v, ok := rep.Totals[c]; ok {
				totals[i] = cellString(v)
			}
		}
	}

	period := ""
	if rep.Period.Start != "" {
		period = rep.Period.Start
		if rep.Period.End != "" {
			period += " — " + rep.Period.End
		}
	}

	// Multi-sheet statutory workbook (P9A/P10/NSSF SF24): map each Report sheet to a doc sheet,
	// reusing the same humanize/cell/totals conversion as the flat table.
	var sheets []docs.ReportSheet
	for _, sh := range rep.Sheets {
		sheets = append(sheets, docs.ReportSheet{
			Name:    sh.Name,
			Columns: humanizeAll(sh.Columns),
			Rows:    rowsToStrings(sh.Rows, sh.Columns),
			Totals:  totalsRow(sh.Totals, sh.Columns),
		})
	}

	return withBranding(&docs.Document{
		Type:               docs.DocTypePayrollReport,
		DocNumber:          docNumber,
		PeriodLabel:        period,
		TenantName:         ti.Name,
		TenantSlug:         ti.Slug,
		TenantEmail:        ti.Email,
		TenantPhone:        ti.Phone,
		TenantAddress:      ti.Address,
		TenantCountry:      ti.Country,
		TenantWebsite:      ti.Website,
		TenantLogoURL:      ti.LogoURL,
		TenantPrimaryColor: ti.PrimaryColor,
		ReportTitle:        humanizeColumn(rep.Report),
		ReportColumns:      headers,
		ReportRows:         rows,
		ReportTotals:       totals,
		Sheets:             sheets,
	}, ti)
}

// humanizeAll maps column keys to display headers.
func humanizeAll(cols []string) []string {
	out := make([]string, len(cols))
	for i, c := range cols {
		out[i] = humanizeColumn(c)
	}
	return out
}

// rowsToStrings projects each map row onto the ordered column keys as strings.
func rowsToStrings(rows []map[string]any, cols []string) [][]string {
	out := make([][]string, 0, len(rows))
	for _, r := range rows {
		row := make([]string, len(cols))
		for i, c := range cols {
			row[i] = cellString(r[c])
		}
		out = append(out, row)
	}
	return out
}

// totalsRow builds a "Total"-prefixed footer row from a totals map, aligned to cols (nil when empty).
func totalsRow(t map[string]any, cols []string) []string {
	if len(t) == 0 {
		return nil
	}
	out := make([]string, len(cols))
	for i, c := range cols {
		if i == 0 {
			out[i] = "Total"
			continue
		}
		if v, ok := t[c]; ok {
			out[i] = cellString(v)
		}
	}
	return out
}

// cellString renders a report cell value (string / number / bool) for display.
func cellString(v any) string {
	if v == nil {
		return ""
	}
	switch t := v.(type) {
	case string:
		return t
	case fmt.Stringer:
		return t.String()
	default:
		return fmt.Sprintf("%v", t)
	}
}

// humanizeColumn turns a snake_case column/report key into a Title Case header.
func humanizeColumn(s string) string {
	parts := strings.Split(s, "_")
	for i, p := range parts {
		if p == "" {
			continue
		}
		parts[i] = strings.ToUpper(p[:1]) + p[1:]
	}
	return strings.Join(parts, " ")
}
