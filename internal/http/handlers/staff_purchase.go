package handlers

import (
	"encoding/json"
	"net/http"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/staffpurchase"
)

// StaffPurchaseHandler serves the POS↔ERP staff-credit endpoints (S2S from pos-api + a reconcile
// view for the admin UI).
type StaffPurchaseHandler struct {
	log *zap.Logger
	svc *staffpurchase.Service
}

func NewStaffPurchaseHandler(log *zap.Logger, svc *staffpurchase.Service) *StaffPurchaseHandler {
	return &StaffPurchaseHandler{log: log.Named("hrm.staff_purchase"), svc: svc}
}

func (h *StaffPurchaseHandler) RegisterRoutes(r chi.Router) {
	r.Post("/hrm/staff-purchases", h.Create)
	r.Get("/hrm/staff-sync/status", h.SyncStatus)
}

// resolveTenant resolves the target tenant: from the JWT tenant claim, or — for S2S (X-API-Key) /
// platform-owner callers — from the X-Tenant-ID header. pos-api calls this with X-API-Key +
// X-Tenant-ID: <tenant>.
func resolveTenant(w http.ResponseWriter, r *http.Request) (uuid.UUID, bool) {
	claims, ok := authclient.ClaimsFromContext(r.Context())
	if !ok || claims == nil {
		writeError(w, http.StatusUnauthorized, "unauthorized", "missing claims")
		return uuid.Nil, false
	}
	var tenantID uuid.UUID
	if tp, err := claims.TenantUUID(); err == nil && tp != nil {
		tenantID = *tp
	}
	if claims.IsService || claims.IsPlatformOwner {
		if hv := r.Header.Get("X-Tenant-ID"); hv != "" {
			if id, err := uuid.Parse(hv); err == nil && id != uuid.Nil {
				tenantID = id
			}
		}
	}
	if tenantID == uuid.Nil {
		writeError(w, http.StatusBadRequest, "bad_request", "tenant id required (X-Tenant-ID for S2S)")
		return uuid.Nil, false
	}
	return tenantID, true
}

type createStaffPurchaseBody struct {
	AuthUserID        string `json:"auth_user_id"`
	Origin            string `json:"origin"`
	POSReference      string `json:"pos_reference"`
	SourceKey         string `json:"source_key"`
	Principal         string `json:"principal"`
	InstallmentAmount string `json:"installment_amount"`
	InstallmentsTotal int    `json:"installments_total"`
	EmployeeEmail     string `json:"employee_email"`
	EmployeeName      string `json:"employee_name"`
}

// Create ingests a POS staff purchase into an ERP recoverable (idempotent on source_key).
func (h *StaffPurchaseHandler) Create(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := resolveTenant(w, r)
	if !ok {
		return
	}
	var body createStaffPurchaseBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	authUserID, err := uuid.Parse(body.AuthUserID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid auth_user_id")
		return
	}
	principal, err := decimal.NewFromString(body.Principal)
	if err != nil || !principal.IsPositive() {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid principal")
		return
	}
	install, _ := decimal.NewFromString(body.InstallmentAmount)

	res, err := h.svc.Create(r.Context(), tenantID, staffpurchase.CreateInput{
		AuthUserID:        authUserID,
		Origin:            body.Origin,
		POSReference:      body.POSReference,
		SourceKey:         body.SourceKey,
		Principal:         principal,
		InstallmentAmount: install,
		InstallmentsTotal: body.InstallmentsTotal,
		EmployeeEmail:     body.EmployeeEmail,
		EmployeeName:      body.EmployeeName,
	})
	if err == staffpurchase.ErrNotEntitled {
		writeError(w, http.StatusForbidden, "feature_not_available", "staff_fund_from_salary is not included in this tenant's plan")
		return
	}
	if err != nil {
		h.log.Error("create staff purchase", zap.Error(err))
		writeError(w, http.StatusUnprocessableEntity, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, res)
}

// SyncStatus returns per-employee staff-purchase outstanding balances for the admin reconcile view.
func (h *StaffPurchaseHandler) SyncStatus(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := resolveTenant(w, r)
	if !ok {
		return
	}
	rows, err := h.svc.SyncStatus(r.Context(), tenantID)
	if err != nil {
		h.log.Error("staff sync status", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "query_failed", "failed to load staff sync status")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}
