package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// Timesheet billing is called only by projects-api, S2S with X-API-Key and X-Tenant-ID, the same
// scheme as project-hours. A user token is refused, so time is billed only through a project
// invoice run.

func (h *AttendanceHandler) registerTimesheetBillingRoutes(ar chi.Router) {
	ar.Post("/timesheets/billing/reserve", h.ReserveTimesheetBilling)
	ar.Post("/timesheets/billing/confirm", h.ConfirmTimesheetBilling)
	ar.Post("/timesheets/billing/release", h.ReleaseTimesheetBilling)
}

// serviceTenant resolves the tenant of an S2S call and refuses any other caller.
func serviceTenant(w http.ResponseWriter, r *http.Request) (uuid.UUID, bool) {
	claims, ok := authclient.ClaimsFromContext(r.Context())
	if !ok || claims == nil || !claims.IsService {
		writeError(w, http.StatusForbidden, "forbidden", "service credentials required")
		return uuid.Nil, false
	}
	return resolveTenant(w, r)
}

type billingBody struct {
	ProjectID  string `json:"project_id"`
	From       string `json:"from"`
	To         string `json:"to"`
	BillingRef string `json:"billing_ref"`
	InvoiceID  string `json:"invoice_id"`
	// IncludeConfirmed (release only) also frees entries confirmed on a void or cancelled invoice.
	IncludeConfirmed bool `json:"include_confirmed"`
}

func decodeBillingBody(w http.ResponseWriter, r *http.Request) (billingBody, uuid.UUID, bool) {
	var b billingBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return b, uuid.Nil, false
	}
	ref, err := uuid.Parse(b.BillingRef)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "billing_ref must be a UUID")
		return b, uuid.Nil, false
	}
	return b, ref, true
}

// ReserveTimesheetBilling godoc
// @Summary Reserve billable project time for an invoice run
// @Description Marks the approved, billable entries of project_id dated from..to (inclusive, at most 366 days) that no run has reserved with billing_ref, then returns every entry carrying billing_ref and billed_invoice_id when the run was already confirmed. S2S only.
// @Tags attendance
// @Accept json
// @Produce json
// @Success 200 {object} attendance.BillingReservation
// @Router /hrm/attendance/timesheets/billing/reserve [post]
func (h *AttendanceHandler) ReserveTimesheetBilling(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := serviceTenant(w, r)
	if !ok {
		return
	}
	b, ref, ok := decodeBillingBody(w, r)
	if !ok {
		return
	}
	projectID, err := uuid.Parse(b.ProjectID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "project_id must be a UUID")
		return
	}
	from, ferr := time.Parse(time.DateOnly, b.From)
	to, terr := time.Parse(time.DateOnly, b.To)
	if ferr != nil || terr != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "from and to must be YYYY-MM-DD")
		return
	}
	res, err := h.svc.ReserveBillableEntries(r.Context(), tenantID, projectID, from, to, ref)
	if errors.Is(err, attendance.ErrBillingPeriod) {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to reserve billable time")
		return
	}
	writeJSON(w, http.StatusOK, res)
}

// ConfirmTimesheetBilling godoc
// @Summary Confirm a billing run with its invoice
// @Description Records invoice_id on every entry carrying billing_ref, replacing an earlier invoice id (a deleted draft's). Idempotent. Returns the number of entries carrying billing_ref. S2S only.
// @Tags attendance
// @Accept json
// @Produce json
// @Success 200 {object} map[string]int
// @Router /hrm/attendance/timesheets/billing/confirm [post]
func (h *AttendanceHandler) ConfirmTimesheetBilling(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := serviceTenant(w, r)
	if !ok {
		return
	}
	b, ref, ok := decodeBillingBody(w, r)
	if !ok {
		return
	}
	invoiceID, err := uuid.Parse(b.InvoiceID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invoice_id must be a UUID")
		return
	}
	n, err := h.svc.ConfirmBilling(r.Context(), tenantID, ref, invoiceID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to confirm billing")
		return
	}
	writeJSON(w, http.StatusOK, map[string]int{"updated": n})
}

// ReleaseTimesheetBilling godoc
// @Summary Release a billing run that produced no invoice
// @Description Clears billing_ref from the entries not confirmed on an invoice, so a later run can bill them. With include_confirmed true it also frees confirmed entries, clearing billed_invoice_id (sent only after treasury shows the invoice void or cancelled). S2S only.
// @Tags attendance
// @Accept json
// @Produce json
// @Success 200 {object} map[string]int
// @Router /hrm/attendance/timesheets/billing/release [post]
func (h *AttendanceHandler) ReleaseTimesheetBilling(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := serviceTenant(w, r)
	if !ok {
		return
	}
	b, ref, ok := decodeBillingBody(w, r)
	if !ok {
		return
	}
	n, err := h.svc.ReleaseBilling(r.Context(), tenantID, ref, b.IncludeConfirmed)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to release billing")
		return
	}
	writeJSON(w, http.StatusOK, map[string]int{"released": n})
}
