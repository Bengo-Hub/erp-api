package reports

import (
	"context"
	"sort"
	"strings"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
)

// section render order for the muster-roll column layout (wingubox parity).
var musterSectionRank = map[string]int{
	"earning_cash":          0,
	"benefit_noncash":       1,
	"deduction_before_tax":  2,
	"tax":                   3,
	"deduction_after_tax":   4,
	"employer_contribution": 5,
}

// musterComp is one distinct payroll component discovered across the period's payslip lines.
type musterComp struct {
	section string
	label   string
	key     string // slug of label, unique per (section,label)
	rank    int    // first-seen sort key
	hasQty  bool
}

// slugify turns a component label into a stable column key (lowercase, alnum + underscore).
func slugify(s string) string {
	var b strings.Builder
	prevUS := false
	for _, r := range strings.ToLower(strings.TrimSpace(s)) {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9':
			b.WriteRune(r)
			prevUS = false
		default:
			if !prevUS && b.Len() > 0 {
				b.WriteByte('_')
				prevUS = true
			}
		}
	}
	return strings.Trim(b.String(), "_")
}

// MusterRoll is the per-employee payroll sign-off sheet for the period with DYNAMIC per-component
// columns pivoted from payslip_line: one column per distinct earning/benefit/statutory/deduction/
// employer-contribution component (plus a Qty column where the component is per-unit), framed by
// Staff No / Employee Name and the derived Gross Pay / Total Statutory / Total Other Ded / Net Pay
// columns, with a Grand Totals row. Columns vary per tenant (their configured components) — the
// backend returns ColumnDefs so the UI renders them with horizontal scroll + Edit-Columns.
func (s *Service) MusterRoll(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	slips, err := s.fetchPayslips(ctx, tenantID, f)
	if err != nil {
		return nil, err
	}
	emps, err := s.employeeMap(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	ids := make([]uuid.UUID, 0, len(slips))
	for _, p := range slips {
		ids = append(ids, p.ID)
	}
	var lines []*ent.PayslipLine
	if len(ids) > 0 {
		lines, err = s.orm.PayslipLine.Query().
			Where(payslipline.TenantID(tenantID), payslipline.PayslipIDIn(ids...)).
			Order(ent.Asc(payslipline.FieldSortOrder)).All(ctx)
		if err != nil {
			return nil, err
		}
	}

	// Discover distinct components (union across all employees), preserving a stable order.
	comps := map[string]*musterComp{}       // (section|label) -> comp
	order := 0                              // monotonic first-seen counter
	lineByPayslip := map[uuid.UUID][]*ent.PayslipLine{}
	for _, l := range lines {
		lineByPayslip[l.PayslipID] = append(lineByPayslip[l.PayslipID], l)
		if _, ok := musterSectionRank[l.Section]; !ok {
			continue // skip relief etc. from the column set
		}
		ck := l.Section + "|" + l.Label
		c, ok := comps[ck]
		if !ok {
			c = &musterComp{section: l.Section, label: l.Label, key: slugify(l.Section[:3] + "_" + l.Label), rank: order}
			comps[ck] = c
			order++
		}
		if l.Quantity.GreaterThan(decimal.Zero) {
			c.hasQty = true
		}
	}

	// Order components by section rank, then first-seen.
	ordered := make([]*musterComp, 0, len(comps))
	for _, c := range comps {
		ordered = append(ordered, c)
	}
	sort.SliceStable(ordered, func(i, j int) bool {
		ri, rj := musterSectionRank[ordered[i].section], musterSectionRank[ordered[j].section]
		if ri != rj {
			return ri < rj
		}
		return ordered[i].rank < ordered[j].rank
	})

	// Build the column layout.
	defs := []ColumnDef{
		{Key: "employee_number", Header: "Staff No.", Sticky: true},
		{Key: "employee_name", Header: "Employee Name", Sticky: true},
	}
	addComps := func(section string) {
		for _, c := range ordered {
			if c.section != section {
				continue
			}
			if c.hasQty {
				defs = append(defs, ColumnDef{Key: c.key + "_qty", Header: c.label + " Qty", Numeric: true})
			}
			defs = append(defs, ColumnDef{Key: c.key, Header: c.label, Money: true})
		}
	}
	addComps("earning_cash")
	addComps("benefit_noncash")
	defs = append(defs, ColumnDef{Key: "gross_pay", Header: "Gross Pay", Money: true})
	addComps("deduction_before_tax")
	addComps("tax")
	defs = append(defs, ColumnDef{Key: "total_statutory", Header: "Total Statutory", Money: true})
	addComps("deduction_after_tax")
	defs = append(defs, ColumnDef{Key: "total_other_ded", Header: "Total Other Ded.", Money: true})
	defs = append(defs, ColumnDef{Key: "net_pay", Header: "Net Pay", Money: true})
	addComps("employer_contribution")

	cols := make([]string, len(defs))
	for i, d := range defs {
		cols[i] = d.Key
	}

	rep := &Report{Report: "Muster Roll", Period: periodMeta(f), Columns: cols, ColumnDefs: defs, Rows: []map[string]any{}}
	totals := map[string]decimal.Decimal{}

	for _, p := range slips {
		e := emps[p.EmployeeID]
		row := map[string]any{"employee_number": empNumber(e), "employee_name": empName(e)}
		// Per-component amounts for this employee.
		amt := map[string]decimal.Decimal{}
		qty := map[string]decimal.Decimal{}
		statutory, otherDed := decimal.Zero, decimal.Zero
		for _, l := range lineByPayslip[p.ID] {
			c, ok := comps[l.Section+"|"+l.Label]
			if !ok {
				continue
			}
			amt[c.key] = amt[c.key].Add(l.CashAmount)
			if c.hasQty {
				qty[c.key] = qty[c.key].Add(l.Quantity)
			}
			switch l.Section {
			case "deduction_before_tax", "tax":
				statutory = statutory.Add(l.CashAmount)
			case "deduction_after_tax":
				otherDed = otherDed.Add(l.CashAmount)
			}
		}
		put := func(key string, v decimal.Decimal) {
			row[key] = money(v)
			totals[key] = totals[key].Add(v)
		}
		for _, c := range ordered {
			if c.hasQty {
				row[c.key+"_qty"] = qty[c.key].String()
				totals[c.key+"_qty"] = totals[c.key+"_qty"].Add(qty[c.key])
			}
			put(c.key, amt[c.key])
		}
		put("gross_pay", p.GrossPay)
		put("total_statutory", statutory)
		put("total_other_ded", otherDed)
		put("net_pay", p.NetPay)
		rep.Rows = append(rep.Rows, row)
	}

	rep.Totals = map[string]any{"count": len(slips)}
	for k, v := range totals {
		rep.Totals[k] = money(v)
	}
	return rep, nil
}

// empNumber returns the employee's HR/payroll number (blank when unset).
func empNumber(e *ent.Employee) string {
	if e == nil || e.EmployeeNumber == nil {
		return ""
	}
	return *e.EmployeeNumber
}
