package handlers

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
)

// emailPayslipsBody is the Email Pay Slips request (mirrors the wingubox flow): an accompanying
// HTML message, the payroll month, and an optional employee subset + scheduled send time.
type emailPayslipsBody struct {
	PaymentPeriod string   `json:"payment_period"`
	Month         string   `json:"month"`
	EmployeeIDs   []string `json:"employee_ids"`
	Message       string   `json:"message"`
	SendTime      string   `json:"send_time"` // optional RFC3339; future = scheduled
}

func (b emailPayslipsBody) period() (time.Time, bool) {
	if p, ok := parsePeriod(b.PaymentPeriod); ok {
		return p, true
	}
	return parsePeriod(b.Month)
}

// EmailPayslips generates each selected employee's payslip PDF for the period and publishes
// an erp.email.requested event (with the PDF as a base64 attachment + the accompanying message)
// to the outbox for notifications-api to deliver. Only employees with a valid email are sent.
//
// A future send_time is honoured by stamping `deliver_at` on the event so the email worker
// can hold it; immediate requests dispatch as soon as the outbox drains.
func (h *DocumentsHandler) EmailPayslips(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var b emailPayslipsBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	period, ok := b.period()
	if !ok {
		writeError(w, http.StatusBadRequest, "bad_request", "a valid payroll month/period is required")
		return
	}
	if h.notify == nil {
		writeError(w, http.StatusServiceUnavailable, "unavailable", "email delivery is not configured")
		return
	}

	// Optional explicit employee subset.
	wanted := map[uuid.UUID]bool{}
	for _, s := range b.EmployeeIDs {
		if id, err := uuid.Parse(s); err == nil {
			wanted[id] = true
		}
	}

	// All payslips for the period (paged high; payroll runs are small per tenant/month).
	payslips, _, err := h.payroll.ListPayslips(r.Context(), scope.TenantID, &period, nil, 1000, 0)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load payslips")
		return
	}

	message := strings.TrimSpace(b.Message)
	if message == "" {
		message = fmt.Sprintf("Please find attached your pay slip for %s.", period.Format("January 2006"))
	}
	var deliverAt *time.Time
	if b.SendTime != "" {
		if t, err := time.Parse(time.RFC3339, b.SendTime); err == nil && t.After(time.Now()) {
			deliverAt = &t
		}
	}

	sent, skipped := 0, 0
	for _, ps := range payslips {
		if len(wanted) > 0 && !wanted[ps.EmployeeID] {
			continue
		}
		emp, eerr := h.payroll.GetEmployee(r.Context(), scope.TenantID, ps.EmployeeID)
		if eerr != nil || emp == nil || strings.TrimSpace(emp.Email) == "" {
			skipped++
			continue
		}
		if err := h.emailOnePayslip(r.Context(), scope.TenantID, ps, emp, period, message, deliverAt); err != nil {
			h.log.Warn("email payslip", zap.String("employee", emp.ID.String()), zap.Error(err))
			skipped++
			continue
		}
		sent++
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"status":   "queued",
		"queued":   sent,
		"skipped":  skipped,
		"period":   period.Format("2006-01"),
		"schedule": b.SendTime,
	})
}

// emailOnePayslip renders one payslip PDF and publishes the email event with it attached.
func (h *DocumentsHandler) emailOnePayslip(ctx context.Context, tenantID uuid.UUID, ps *ent.Payslip, emp *ent.Employee, period time.Time, message string, deliverAt *time.Time) error {
	pdf, filename, mime, err := h.payslipPDFBytes(ctx, tenantID, ps, emp)
	if err != nil {
		return fmt.Errorf("render pdf: %w", err)
	}
	greeting := strings.TrimSpace(emp.FirstName + " " + emp.LastName)
	body := fmt.Sprintf("<p>Dear %s,</p><p>%s</p><p>Regards,<br/>Payroll</p>", greeting, message)

	req := events.EmailRequest{
		To:      []string{emp.Email},
		Subject: fmt.Sprintf("Your payslip for %s", period.Format("January 2006")),
		Body:    body,
		HTML:    true,
		Attachments: []events.EmailAttachment{{
			Filename:    filename,
			ContentType: mime,
			ContentB64:  base64.StdEncoding.EncodeToString(pdf),
		}},
		DeliverAt: deliverAt,
	}
	// aggregate_id MUST be a UUID (the shared-events poller scans it into uuid.UUID); use the payslip id.
	return h.notify.RequestEmail(ctx, tenantID, ps.ID.String(), req)
}
