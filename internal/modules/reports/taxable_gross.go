package reports

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
)

// taxableGross returns each payslip's gross pay without its non-taxable earnings (per diem and
// other income not chargeable to PAYE). The KRA PAYE returns (P9, P9A, P10, P10A) declare this
// figure: gross less the allowable deductions must give the chargeable pay. The non-taxable part
// is read from the payslip's stored earning lines, so nothing is recomputed and a payslip without
// such lines keeps its gross.
func (s *Service) taxableGross(ctx context.Context, tenantID uuid.UUID, slips []*ent.Payslip) (map[uuid.UUID]decimal.Decimal, error) {
	out := make(map[uuid.UUID]decimal.Decimal, len(slips))
	ids := make([]uuid.UUID, 0, len(slips))
	for _, p := range slips {
		out[p.ID] = p.GrossPay
		ids = append(ids, p.ID)
	}
	for _, chunk := range idChunks(ids) {
		lines, err := s.orm.PayslipLine.Query().Where(
			payslipline.TenantID(tenantID), payslipline.PayslipIDIn(chunk...),
			payslipline.Section("earning_cash"), payslipline.Taxable(false)).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, l := range lines {
			out[l.PayslipID] = out[l.PayslipID].Sub(l.CashAmount)
		}
	}
	return out, nil
}
