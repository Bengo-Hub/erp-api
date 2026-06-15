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
	}, ti)
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
