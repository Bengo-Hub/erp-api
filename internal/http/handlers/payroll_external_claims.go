package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

// Claims raised by other services (logistics per diem for staff drivers today) and the
// per diem policy HR edits. See payroll/external_claims.go for the rules.

func (h *PayrollHandler) registerExternalClaimRoutes(r chi.Router) {
	r.Post("/hrm/claims/external", h.CreateExternalClaim)
	r.Get("/hrm/claims/external", h.GetExternalClaim)
	r.Get("/hrm/payroll/per-diem-policy", h.GetPerDiemPolicy)
	r.Put("/hrm/payroll/per-diem-policy", h.SavePerDiemPolicy)
}

// externalCaller resolves the tenant for a service caller (X-API-Key + X-Tenant-ID) or a
// payroll manager. Other users may not raise claims on someone else's behalf.
func externalCaller(w http.ResponseWriter, r *http.Request) (uuid.UUID, bool) {
	claims, ok := authclient.ClaimsFromContext(r.Context())
	if !ok || claims == nil {
		writeError(w, http.StatusUnauthorized, "unauthorized", "missing claims")
		return uuid.Nil, false
	}
	if !claims.IsService && !claims.IsPlatformOwner {
		scope, ok := scopeFromRequest(w, r)
		if !ok || !requirePermission(w, scope, permPayrollManage) {
			return uuid.Nil, false
		}
		return scope.TenantID, true
	}
	return resolveTenant(w, r)
}

type externalClaimBody struct {
	AuthUserID  string         `json:"auth_user_id"`
	Source      string         `json:"source"`
	SourceKey   string         `json:"source_key"`
	ClaimType   string         `json:"claim_type"`
	Days        float64        `json:"days"`
	Amount      string         `json:"amount"`
	DistanceKm  float64        `json:"distance_km"`
	StartedAt   *time.Time     `json:"started_at"`
	EndedAt     *time.Time     `json:"ended_at"`
	Description string         `json:"description"`
	Reference   map[string]any `json:"reference"`
}

// CreateExternalClaim raises an expense claim for an employee from another service.
// Idempotent on source_key: 201 when created, 200 with the existing claim on replay.
func (h *PayrollHandler) CreateExternalClaim(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := externalCaller(w, r)
	if !ok {
		return
	}
	var body externalClaimBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	userID, err := uuid.Parse(body.AuthUserID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid auth_user_id")
		return
	}
	amount := decimal.Zero
	if strings.TrimSpace(body.Amount) != "" {
		if amount, err = decimal.NewFromString(body.Amount); err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "invalid amount")
			return
		}
	}
	res, err := h.svc.CreateExternalClaim(r.Context(), tenantID, payroll.ExternalClaimInput{
		AuthUserID:  userID,
		Source:      body.Source,
		SourceKey:   body.SourceKey,
		ClaimType:   body.ClaimType,
		Days:        body.Days,
		Amount:      amount,
		DistanceKm:  body.DistanceKm,
		StartedAt:   body.StartedAt,
		EndedAt:     body.EndedAt,
		Description: body.Description,
		Reference:   body.Reference,
	})
	switch {
	case errors.Is(err, payroll.ErrNotAnEmployee):
		writeError(w, http.StatusUnprocessableEntity, "not_an_employee", "this user has no employee record in HR")
		return
	case errors.Is(err, payroll.ErrPerDiemDisabled):
		writeError(w, http.StatusUnprocessableEntity, "per_diem_disabled", "per diem is not set up in HR payroll settings")
		return
	case errors.Is(err, payroll.ErrNotEligible):
		writeError(w, http.StatusUnprocessableEntity, "not_eligible", "trip is shorter than the per diem distance threshold")
		return
	case err != nil:
		h.log.Warn("external claim", zap.Error(err))
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	status := http.StatusOK
	if res.Created {
		status = http.StatusCreated
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), tenantID, res.Claim.EmployeeID)
	writeJSON(w, status, externalClaimView(res.Claim, name))
}

// GetExternalClaim returns the claim raised for ?source_key=, so the caller can show its status.
func (h *PayrollHandler) GetExternalClaim(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := externalCaller(w, r)
	if !ok {
		return
	}
	key := strings.TrimSpace(r.URL.Query().Get("source_key"))
	if key == "" {
		writeError(w, http.StatusBadRequest, "bad_request", "source_key is required")
		return
	}
	c, err := h.svc.FindExternalClaim(r.Context(), tenantID, key)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "query_failed", "failed to load claim")
		return
	}
	if c == nil {
		writeError(w, http.StatusNotFound, "not_found", "no claim for this source_key")
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), tenantID, c.EmployeeID)
	writeJSON(w, http.StatusOK, externalClaimView(c, name))
}

func externalClaimView(c *ent.ExpenseClaim, name string) map[string]any {
	v := claimView(c, name)
	if c.Metadata != nil {
		v["metadata"] = c.Metadata
	}
	return v
}

// GetPerDiemPolicy returns the tenant's per diem policy. Service callers may read it too.
func (h *PayrollHandler) GetPerDiemPolicy(w http.ResponseWriter, r *http.Request) {
	claims, _ := authclient.ClaimsFromContext(r.Context())
	var tenantID uuid.UUID
	if claims != nil && claims.IsService {
		id, ok := resolveTenant(w, r)
		if !ok {
			return
		}
		tenantID = id
	} else {
		scope, ok := scopeFromRequest(w, r)
		if !ok || !requirePermission(w, scope, permPayrollView) {
			return
		}
		tenantID = scope.TenantID
	}
	p, err := h.svc.GetPerDiemPolicy(r.Context(), tenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "query_failed", "failed to load per diem policy")
		return
	}
	writeJSON(w, http.StatusOK, p)
}

// SavePerDiemPolicy replaces the tenant's per diem policy.
func (h *PayrollHandler) SavePerDiemPolicy(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var p payroll.PerDiemPolicy
	if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	saved, err := h.svc.SavePerDiemPolicy(r.Context(), scope.TenantID, p)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_policy", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, saved)
}
