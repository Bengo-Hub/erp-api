package handlers

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

// This file holds the conditional-by-claim-type line tables (itemized ClaimItems for
// other/reimbursement, MileageRoutes for mileage) plus the claim attachment upload — the
// pieces that bring the claims form to full Wingubox parity.

func claimURLID(w http.ResponseWriter, r *http.Request) (uuid.UUID, bool) {
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid claim id")
		return uuid.Nil, false
	}
	return id, true
}

// ---- Claim items (itemized lines) ----

type claimItemBody struct {
	ExpenseType string `json:"expense_type"`
	Description string `json:"description"`
	Quantity    string `json:"quantity"`
	UnitCost    string `json:"unit_cost"`
	Amount      string `json:"amount"`
	// Date the expense was incurred (YYYY-MM-DD), optional.
	Date string `json:"date"`
}

func claimItemView(it *ent.ClaimItem) map[string]any {
	v := map[string]any{
		"id":               it.ID,
		"expense_claim_id": it.ExpenseClaimID,
		"expense_type":     it.ExpenseType,
		"amount":           it.Amount.StringFixed(2),
		"created_at":       it.CreatedAt.Format(time.RFC3339),
	}
	if it.Description != nil {
		v["description"] = *it.Description
	}
	if it.ItemDate != nil {
		v["date"] = it.ItemDate.Format("2006-01-02")
	}
	return v
}

func (h *PayrollHandler) ListClaimItems(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, ok := claimURLID(w, r)
	if !ok {
		return
	}
	rows, err := h.svc.ListClaimItems(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusBadRequest, "list_failed", err.Error())
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, it := range rows {
		out = append(out, claimItemView(it))
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": out, "data": out})
}

func (h *PayrollHandler) CreateClaimItem(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, ok := claimURLID(w, r)
	if !ok {
		return
	}
	var body claimItemBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in := payroll.ClaimItemInput{
		ExpenseType: body.ExpenseType,
		Description: body.Description,
		Quantity:    parseDec(body.Quantity),
		UnitCost:    parseDec(body.UnitCost),
		Amount:      parseDec(body.Amount),
	}
	if body.Date != "" {
		d, err := parseDate(body.Date)
		if err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "invalid date (want YYYY-MM-DD)")
			return
		}
		in.Date = &d
	}
	it, err := h.svc.CreateClaimItem(r.Context(), scope.TenantID, id, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, claimItemView(it))
}

func (h *PayrollHandler) DeleteClaimItem(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, ok := claimURLID(w, r)
	if !ok {
		return
	}
	itemID, err := uuid.Parse(chi.URLParam(r, "itemId"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid item id")
		return
	}
	if err := h.svc.DeleteClaimItem(r.Context(), scope.TenantID, id, itemID); err != nil {
		writeError(w, http.StatusBadRequest, "delete_failed", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Mileage routes ----

type mileageRouteBody struct {
	Date         string `json:"date"`
	From         string `json:"from"`
	To           string `json:"to"`
	Distance     string `json:"distance"`
	Rate         string `json:"rate"`
	Amount       string `json:"amount"`
	FromLocation string `json:"from_location"`
	ToLocation   string `json:"to_location"`
}

func mileageRouteView(rt *ent.MileageRoute) map[string]any {
	v := map[string]any{
		"id":               rt.ID,
		"expense_claim_id": rt.ExpenseClaimID,
		"from":             rt.FromLocation,
		"from_location":    rt.FromLocation,
		"to":               rt.ToLocation,
		"to_location":      rt.ToLocation,
		"distance":         rt.Distance.StringFixed(2),
		"rate":             rt.Rate.StringFixed(2),
		"amount":           rt.Amount.StringFixed(2),
		"created_at":       rt.CreatedAt.Format(time.RFC3339),
	}
	if rt.RouteDate != nil {
		v["date"] = rt.RouteDate.Format("2006-01-02")
	}
	return v
}

func (h *PayrollHandler) ListMileageRoutes(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, ok := claimURLID(w, r)
	if !ok {
		return
	}
	rows, err := h.svc.ListMileageRoutes(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusBadRequest, "list_failed", err.Error())
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, rt := range rows {
		out = append(out, mileageRouteView(rt))
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": out, "data": out})
}

func (h *PayrollHandler) CreateMileageRoute(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, ok := claimURLID(w, r)
	if !ok {
		return
	}
	var body mileageRouteBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	from := body.From
	if from == "" {
		from = body.FromLocation
	}
	to := body.To
	if to == "" {
		to = body.ToLocation
	}
	in := payroll.MileageRouteInput{
		FromLocation: from,
		ToLocation:   to,
		Distance:     parseDec(body.Distance),
		Rate:         parseDec(body.Rate),
		Amount:       parseDec(body.Amount),
	}
	if body.Date != "" {
		if d, err := parseDate(body.Date); err == nil {
			in.RouteDate = &d
		}
	}
	rt, err := h.svc.CreateMileageRoute(r.Context(), scope.TenantID, id, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, mileageRouteView(rt))
}

func (h *PayrollHandler) DeleteMileageRoute(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, ok := claimURLID(w, r)
	if !ok {
		return
	}
	routeID, err := uuid.Parse(chi.URLParam(r, "routeId"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid route id")
		return
	}
	if err := h.svc.DeleteMileageRoute(r.Context(), scope.TenantID, id, routeID); err != nil {
		writeError(w, http.StatusBadRequest, "delete_failed", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Attachment upload ----

// UploadClaimAttachment stores a claim receipt/attachment in the per-tenant media store and
// records its relative path on the claim.
func (h *PayrollHandler) UploadClaimAttachment(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	if !h.media.Enabled() {
		writeError(w, http.StatusServiceUnavailable, "media_unavailable", "media storage not configured")
		return
	}
	id, ok := claimURLID(w, r)
	if !ok {
		return
	}
	if err := r.ParseMultipartForm(10 << 20); err != nil { // 10 MiB cap
		writeError(w, http.StatusBadRequest, "bad_request", "invalid multipart form")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "file is required")
		return
	}
	defer func() { _ = file.Close() }()
	existing, err := h.svc.GetClaim(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "claim not found")
		return
	}
	rel, err := h.media.SaveClaimAttachment(r.Context(), scope.TenantID, id, header.Filename, file)
	if err != nil {
		writeError(w, http.StatusBadRequest, "upload_failed", err.Error())
		return
	}
	if _, err := h.svc.SetClaimAttachment(r.Context(), scope.TenantID, id, rel); err != nil {
		writeError(w, http.StatusBadRequest, "save_failed", err.Error())
		return
	}
	// The replaced receipt is deleted once the claim points at the new one.
	if existing.AttachmentURL != nil {
		if err := h.media.Release(r.Context(), *existing.AttachmentURL, rel); err != nil {
			h.log.Warn("replaced claim attachment not deleted", zap.Error(err))
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"attachment_url": h.media.URL(rel), "attachment_path": rel})
}

// parseDec parses a decimal string, returning zero on empty/invalid (line inputs are lenient;
// the service re-derives amount = qty×cost / distance×rate when amount is absent).
func parseDec(s string) decimal.Decimal {
	if s == "" {
		return decimal.Zero
	}
	d, err := decimal.NewFromString(s)
	if err != nil {
		return decimal.Zero
	}
	return d
}
