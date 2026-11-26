package payroll

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/contract"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
)

// paidMonth is one earlier payslip's value for a month.
type paidMonth struct {
	period time.Time
	amount decimal.Decimal
}

// gratuityHistory is what the gratuity rules need about an employee, loaded only for employees
// with a gratuity earning assigned.
type gratuityHistory struct {
	contracts []*ent.Contract
	joined    *time.Time
	gross     []paidMonth // gross pay of earlier payslips
	paid      []paidMonth // gratuity paid on earlier payslips (taken out of their gross)
	excluded  []paidMonth // gratuity left out of tax on earlier payslips
}

// isGratuityStatus reports whether a component's taxable status is one of the gratuity rules.
func isGratuityStatus(s string) bool { return s == TaxableGratuity || s == TaxableGratuityPension }

// loadGratuityHistory reads contracts, date joined, earlier gross pay and earlier gratuity
// exclusions for the employees that have a gratuity earning assigned. Nothing is read when none do.
func (s *Service) loadGratuityHistory(ctx context.Context, tenantID uuid.UUID, in *runInputs) error {
	gratuityComponents := map[uuid.UUID]bool{}
	for id, rc := range in.components {
		if isGratuityStatus(rc.TaxableStatus) {
			gratuityComponents[id] = true
		}
	}
	if len(gratuityComponents) == 0 {
		return nil
	}
	empIDs := map[uuid.UUID]bool{}
	for emp, rows := range in.benefits {
		for _, b := range rows {
			if b.ComponentID != nil && gratuityComponents[*b.ComponentID] {
				empIDs[emp] = true
			}
		}
	}
	if len(empIDs) == 0 {
		return nil
	}
	in.gratuity = map[uuid.UUID]*gratuityHistory{}
	for id := range empIDs {
		in.gratuity[id] = &gratuityHistory{}
	}
	compIDs := make([]uuid.UUID, 0, len(gratuityComponents))
	for id := range gratuityComponents {
		compIDs = append(compIDs, id)
	}
	for _, chunk := range chunkIDs(empIDs) {
		contracts, err := s.orm.Contract.Query().
			Where(contract.TenantID(tenantID), contract.EmployeeIDIn(chunk...)).All(ctx)
		if err != nil {
			return fmt.Errorf("contracts: %w", err)
		}
		for _, c := range contracts {
			in.gratuity[c.EmployeeID].contracts = append(in.gratuity[c.EmployeeID].contracts, c)
		}
		hrs, err := s.orm.HRDetails.Query().
			Where(hrdetails.TenantID(tenantID), hrdetails.EmployeeIDIn(chunk...)).All(ctx)
		if err != nil {
			return fmt.Errorf("hr details: %w", err)
		}
		for _, h := range hrs {
			if h.DateJoined != nil {
				in.gratuity[h.EmployeeID].joined = h.DateJoined
			}
		}
		slips, err := s.orm.Payslip.Query().
			Where(payslip.TenantID(tenantID), payslip.EmployeeIDIn(chunk...), payslip.DeleteStatus(false),
				payslip.PaymentPeriodNotNil(), payslip.ApprovalStatusNEQ("rejected")).
			Select(payslip.FieldID, payslip.FieldEmployeeID, payslip.FieldPaymentPeriod, payslip.FieldGrossPay).All(ctx)
		if err != nil {
			return fmt.Errorf("earlier payslips: %w", err)
		}
		slipOwner := map[uuid.UUID]*ent.Payslip{}
		for _, p := range slips {
			slipOwner[p.ID] = p
			h := in.gratuity[p.EmployeeID]
			h.gross = append(h.gross, paidMonth{period: *p.PaymentPeriod, amount: p.GrossPay})
		}
		slipIDs := make([]uuid.UUID, 0, len(slips))
		for id := range slipOwner {
			slipIDs = append(slipIDs, id)
		}
		for start := 0; start < len(slipIDs); start += runChunk {
			end := min(start+runChunk, len(slipIDs))
			lines, err := s.orm.PayslipLine.Query().
				Where(payslipline.TenantID(tenantID), payslipline.PayslipIDIn(slipIDs[start:end]...),
					payslipline.ComponentIDIn(compIDs...)).All(ctx)
			if err != nil {
				return fmt.Errorf("earlier gratuity lines: %w", err)
			}
			for _, l := range lines {
				p := slipOwner[l.PayslipID]
				h := in.gratuity[p.EmployeeID]
				h.paid = append(h.paid, paidMonth{period: *p.PaymentPeriod, amount: l.CashAmount})
				if ex := l.CashAmount.Sub(l.TaxableAmount); ex.IsPositive() {
					h.excluded = append(h.excluded, paidMonth{period: *p.PaymentPeriod, amount: ex})
				}
			}
		}
	}
	return nil
}

// facts builds the gratuity facts for one period. emoluments is this period's pay without the
// gratuity; pensionMember marks a registered pension scheme contributor.
func (h *gratuityHistory) facts(period time.Time, emoluments decimal.Decimal, pensionMember bool) gratuityFacts {
	f := gratuityFacts{PensionMember: pensionMember}
	if h == nil {
		return f
	}
	periodEnd := period.AddDate(0, 1, -1)
	// The contract in force for the period, else the latest one that ended before it.
	var cur *ent.Contract
	curCovers := false
	for _, c := range h.contracts {
		if c.StartDate == nil || c.StartDate.After(periodEnd) {
			continue
		}
		covers := c.EndDate == nil || !c.EndDate.Before(period)
		if cur == nil || (covers && !curCovers) || (covers == curCovers && c.StartDate.After(*cur.StartDate)) {
			cur, curCovers = c, covers
		}
	}
	earliest := h.joined
	for _, c := range h.contracts {
		if c.StartDate != nil && (earliest == nil || c.StartDate.Before(*earliest)) {
			earliest = c.StartDate
		}
	}
	f.ServiceStart = earliest
	from := earliest
	if cur != nil {
		f.ContractStart, f.ContractEnd = cur.StartDate, cur.EndDate
		from = cur.StartDate
	}
	f.Emoluments = emoluments
	for _, m := range h.gross {
		if m.period.Before(period) && (from == nil || !m.period.Before(monthStart(*from))) {
			f.Emoluments = f.Emoluments.Add(m.amount)
		}
	}
	for _, m := range h.paid {
		if m.period.Before(period) && (from == nil || !m.period.Before(monthStart(*from))) {
			f.Emoluments = f.Emoluments.Sub(m.amount)
		}
	}
	for _, m := range h.excluded {
		if m.period.Before(period) && (from == nil || !m.period.Before(monthStart(*from))) {
			f.AlreadyExcluded = f.AlreadyExcluded.Add(m.amount)
		}
	}
	return f
}

func monthStart(t time.Time) time.Time { return time.Date(t.Year(), t.Month(), 1, 0, 0, 0, 0, time.UTC) }
