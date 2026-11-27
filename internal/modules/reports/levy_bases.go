package reports

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
)

// The payroll run stores, on each statutory line, the base that levy was charged on (the line's
// taxable_amount): nssf_t1 holds the NSSF pensionable earnings, shif the SHIF gross salary,
// housing_levy the Housing Levy gross salary. Each earning can count for some levies and not
// others, so these bases can differ from gross pay. Payslips run before the bases were stored
// show gross pay, as the returns always did.

// slipLevies is what the returns read from one payslip's lines.
type slipLevies struct {
	nssfBase, shifBase, ahlBase *decimal.Decimal
	ahlEmployer                 *decimal.Decimal
}

// base returns a stored base, else gross pay.
func base(v *decimal.Decimal, gross decimal.Decimal) decimal.Decimal {
	if v != nil {
		return *v
	}
	return gross
}

// ahlEmployerOf is the Housing Levy employer share: the run's employer line, else the employee
// share (payslips run before that line existed, when the employer matched it).
func (l slipLevies) ahlEmployerOf(p *ent.Payslip) decimal.Decimal {
	if l.ahlEmployer != nil {
		return *l.ahlEmployer
	}
	return p.HousingLevy
}

// levyLines loads the levy bases and the Housing Levy employer share of the payslips.
func (s *Service) levyLines(ctx context.Context, tenantID uuid.UUID, slips []*ent.Payslip) (map[uuid.UUID]slipLevies, error) {
	out := map[uuid.UUID]slipLevies{}
	ids := make([]uuid.UUID, 0, len(slips))
	for _, p := range slips {
		ids = append(ids, p.ID)
	}
	for _, chunk := range idChunks(ids) {
		lines, err := s.orm.PayslipLine.Query().Where(payslipline.TenantID(tenantID), payslipline.PayslipIDIn(chunk...),
			payslipline.CodeIn("nssf_t1", "shif", "housing_levy", "housing_levy_employer")).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, l := range lines {
			v := out[l.PayslipID]
			taxable, employer := l.TaxableAmount, l.EmployerAmount
			switch l.Code {
			case "nssf_t1":
				if taxable.IsPositive() {
					v.nssfBase = &taxable
				}
			case "shif":
				if taxable.IsPositive() {
					v.shifBase = &taxable
				}
			case "housing_levy":
				if taxable.IsPositive() {
					v.ahlBase = &taxable
				}
			case "housing_levy_employer":
				v.ahlEmployer = &employer
			}
			out[l.PayslipID] = v
		}
	}
	return out, nil
}
