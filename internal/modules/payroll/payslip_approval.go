package payroll

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
)

// SetPayslipsApproval transitions the approval_status of all (non-deleted) payslips for a period
// — the explicit review step between processing and disbursement (draft/pending -> approved |
// rejected). Optionally scoped to an outlet. Returns the number of payslips updated.
func (s *Service) SetPayslipsApproval(ctx context.Context, tenantID uuid.UUID, period time.Time, outletID *uuid.UUID, status string) (int, error) {
	switch status {
	case "approved", "rejected", "pending", "draft":
	default:
		return 0, fmt.Errorf("payroll: invalid approval status %q", status)
	}
	q := s.orm.Payslip.Update().Where(
		payslip.TenantID(tenantID),
		payslip.PaymentPeriod(period),
		payslip.DeleteStatus(false),
	)
	if outletID != nil && *outletID != uuid.Nil {
		q = q.Where(payslip.OutletID(*outletID))
	}
	return q.SetApprovalStatus(status).Save(ctx)
}
