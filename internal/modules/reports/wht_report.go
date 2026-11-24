package reports

import (
	"context"
	"fmt"
	"sort"

	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/consultantvoucher"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
)

// whtRow is one payee, residency and rate group of withheld tax.
type whtRow struct {
	EmployeeID uuid.UUID       `json:"employee_id"`
	IsResident bool            `json:"is_resident"`
	WhtRate    decimal.Decimal `json:"wht_rate"`
	Vouchers   int             `json:"vouchers"`
	Gross      decimal.Decimal `json:"gross"`
	Withheld   decimal.Decimal `json:"withheld"`
	Net        decimal.Decimal `json:"net"`
}

// WithholdingTax is the withholding tax return: tax withheld on approved or paid consultant
// payment vouchers in the period, one row per payee, residency and rate, summed in SQL. A
// voucher falls in the period by its payment period, else its approval date. PAYE on
// emoluments is reported by the P10 and P9 returns, not here.
func (s *Service) WithholdingTax(ctx context.Context, tenantID uuid.UUID, f Filter) (*Report, error) {
	var groups []whtRow
	err := s.orm.ConsultantVoucher.Query().
		Where(
			consultantvoucher.TenantID(tenantID),
			consultantvoucher.DeleteStatus(false),
			consultantvoucher.StatusIn(consultantvoucher.StatusApproved, consultantvoucher.StatusPaid),
			func(sel *entsql.Selector) {
				when := fmt.Sprintf("COALESCE(%s, %s, %s)", sel.C(consultantvoucher.FieldPeriod),
					sel.C(consultantvoucher.FieldApprovedAt), sel.C(consultantvoucher.FieldCreatedAt))
				sel.Where(entsql.P(func(b *entsql.Builder) {
					b.WriteString(when).WriteString(" >= ").Arg(f.Start).
						WriteString(" AND ").WriteString(when).WriteString(" < ").Arg(f.End)
				}))
			},
		).
		GroupBy(consultantvoucher.FieldEmployeeID, consultantvoucher.FieldIsResident, consultantvoucher.FieldWhtRate).
		Aggregate(
			func(sel *entsql.Selector) string { return entsql.As("COUNT(*)", "vouchers") },
			sumAs("gross", consultantvoucher.FieldGrossAmount),
			sumAs("withheld", consultantvoucher.FieldWhtAmount),
			sumAs("net", consultantvoucher.FieldNetAmount),
		).
		Scan(ctx, &groups)
	if err != nil {
		return nil, fmt.Errorf("reports: withholding tax: %w", err)
	}

	ids := make([]uuid.UUID, 0, len(groups))
	seen := map[uuid.UUID]bool{}
	for _, g := range groups {
		if !seen[g.EmployeeID] {
			seen[g.EmployeeID] = true
			ids = append(ids, g.EmployeeID)
		}
	}
	names, pins := map[uuid.UUID]string{}, map[uuid.UUID]string{}
	for _, chunk := range idChunks(ids) {
		emps, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(chunk...)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("reports: withholding tax payees: %w", err)
		}
		for _, e := range emps {
			names[e.ID], pins[e.ID] = empName(e), e.PinNo
		}
	}
	sort.SliceStable(groups, func(i, j int) bool { return names[groups[i].EmployeeID] < names[groups[j].EmployeeID] })

	rep := &Report{
		Report: "withholding_tax",
		Period: periodMeta(f),
		Columns: []string{"payee_name", "payee_pin", "payment_type", "residency", "vouchers",
			"gross_amount", "withholding_rate", "withholding_tax", "net_payment"},
		Rows: []map[string]any{},
	}
	gross, withheld, net, count := decimal.Zero, decimal.Zero, decimal.Zero, 0
	for _, g := range groups {
		residency := "Resident"
		if !g.IsResident {
			residency = "Non-resident"
		}
		rep.Rows = append(rep.Rows, map[string]any{
			"payee_name":       names[g.EmployeeID],
			"payee_pin":        pins[g.EmployeeID],
			"payment_type":     "Consultancy fees",
			"residency":        residency,
			"vouchers":         g.Vouchers,
			"gross_amount":     money(g.Gross),
			"withholding_rate": g.WhtRate.Mul(decimal.NewFromInt(100)).Round(2).String(),
			"withholding_tax":  money(g.Withheld),
			"net_payment":      money(g.Net),
		})
		gross, withheld, net = gross.Add(g.Gross), withheld.Add(g.Withheld), net.Add(g.Net)
		count += g.Vouchers
	}
	rep.Totals = map[string]any{
		"vouchers": count, "gross_amount": money(gross), "withholding_tax": money(withheld), "net_payment": money(net),
	}
	return rep, nil
}
