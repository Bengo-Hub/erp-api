package payroll

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

// buildBatchRef mirrors the legacy treasury_integration batch_ref format:
//   payroll-{tenant}-{YYYY-MM}-{outlet|all}
func buildBatchRef(tenantID uuid.UUID, period time.Time, outletID uuid.UUID) string {
	outlet := "all"
	if outletID != uuid.Nil {
		outlet = outletID.String()
	}
	return fmt.Sprintf("payroll-%s-%s-%s", tenantID, period.Format("2006-01"), outlet)
}

func (d *Disburser) loadEmployees(ctx context.Context, tenantID uuid.UUID, slips []*ent.Payslip) (map[uuid.UUID]*ent.Employee, error) {
	ids := make([]uuid.UUID, 0, len(slips))
	for _, s := range slips {
		ids = append(ids, s.EmployeeID)
	}
	rows, err := d.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.IDIn(ids...)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("disburse: load employees: %w", err)
	}
	m := make(map[uuid.UUID]*ent.Employee, len(rows))
	for _, e := range rows {
		m[e.ID] = e
	}
	return m, nil
}

// buildPayrollEvent constructs the erp.payroll.processed payload, byte-compatible with the
// Django publish_and_disburse shape (integrations.md §1). Money is sent as decimal STRINGS
// (gaps §2.1). Returns the payload + net total.
func buildPayrollEvent(slips []*ent.Payslip, empByID map[uuid.UUID]*ent.Employee, p DisburseParams, batchRef string) (map[string]any, decimal.Decimal) {
	lines := make([]map[string]any, 0, len(slips))
	gross := decimal.Zero
	net := decimal.Zero

	for _, s := range slips {
		nssf := s.NssfEmployeeTier1.Add(s.NssfEmployeeTier2)
		gross = gross.Add(s.GrossPay)
		net = net.Add(s.NetPay)

		empRef := s.EmployeeID.String()
		recipientID := s.EmployeeID.String()
		if emp, ok := empByID[s.EmployeeID]; ok {
			if emp.EmployeeNumber != nil && *emp.EmployeeNumber != "" {
				empRef = *emp.EmployeeNumber
			}
			if emp.UserID != nil {
				recipientID = emp.UserID.String()
			}
		}

		lines = append(lines, map[string]any{
			"employee_id":  recipientID,
			"employee_ref": empRef,
			"gross":        s.GrossPay.StringFixed(2),
			"net_pay":      s.NetPay.StringFixed(2),
			"statutory": map[string]any{
				"paye":    s.Paye.StringFixed(2),
				"nhif":    s.ShifOrNhifContribution.StringFixed(2),
				"nssf":    nssf.StringFixed(2),
				"housing": s.HousingLevy.StringFixed(2),
			},
		})
	}
	deductions := gross.Sub(net)

	outletStr := ""
	if p.OutletID != uuid.Nil {
		outletStr = p.OutletID.String()
	}

	payload := map[string]any{
		"tenant_id": p.TenantID.String(),
		"outlet_id": outletStr,
		"period":    p.Period.Format("2006-01-02"),
		"currency":  "KES",
		"totals": map[string]any{
			"gross":      gross.StringFixed(2),
			"deductions": deductions.StringFixed(2),
			"net":        net.StringFixed(2),
		},
		"lines":       lines,
		"cost_center": "",
		"batch_ref":   batchRef,
	}
	return payload, net
}

// buildPayouts converts the event lines into treasury payout requests (net pay > 0 only),
// mirroring the legacy publish_and_disburse payout shape.
func buildPayouts(payload map[string]any, batchRef string, period time.Time) []treasury.Payout {
	lines, _ := payload["lines"].([]map[string]any)
	out := make([]treasury.Payout, 0, len(lines))
	for _, l := range lines {
		netStr, _ := l["net_pay"].(string)
		net, err := decimal.NewFromString(netStr)
		if err != nil || net.LessThanOrEqual(decimal.Zero) {
			continue
		}
		recipient, _ := l["employee_id"].(string)
		ref, _ := l["employee_ref"].(string)
		out = append(out, treasury.Payout{
			RecipientID:   recipient,
			Amount:        net.StringFixed(2),
			Currency:      "KES",
			PaymentMethod: "bank_transfer",
			ReferenceID:   fmt.Sprintf("%s-%s", batchRef, recipient),
			Description:   fmt.Sprintf("Salary %s - %s", period.Format("2006-01"), ref),
		})
	}
	return out
}
