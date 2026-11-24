package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/business"
)

// Business config RBAC permission codes.
const (
	permBusinessView   = "business.view"
	permBusinessManage = "business.manage"
)

// BusinessHandler serves /api/v1/business/* (slim per-tenant config + doc numbering).
type BusinessHandler struct {
	log *zap.Logger
	svc *business.Service
}

func NewBusinessHandler(log *zap.Logger, svc *business.Service) *BusinessHandler {
	return &BusinessHandler{log: log.Named("business"), svc: svc}
}

func (h *BusinessHandler) RegisterRoutes(r chi.Router) {
	r.Route("/business", func(br chi.Router) {
		br.Get("/settings", h.GetSettings)
		br.Put("/settings", h.UpsertSettings)

		br.Get("/sequences", h.ListSequences)
		br.Put("/sequences", h.UpsertSequence)
		br.Post("/sequences/{docType}/next", h.NextNumber)
	})
}

func (h *BusinessHandler) GetSettings(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBusinessView) {
		return
	}
	row, err := h.svc.GetSettings(r.Context(), scope.TenantID)
	if ent.IsNotFound(err) {
		writeJSON(w, http.StatusOK, map[string]any{"settings": nil})
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load settings")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"settings": row})
}

type settingsBody struct {
	LegalName               string `json:"legal_name"`
	KRAPin                  string `json:"kra_pin"`
	NSSFEmployerNo          string `json:"nssf_employer_no"`
	SHIFEmployerNo          string `json:"shif_employer_no"`
	ContactEmail            string `json:"contact_email"`
	ContactPhone            string `json:"contact_phone"`
	PostalAddress           string `json:"postal_address"`
	PhysicalAddress         string `json:"physical_address"`
	FinancialYearStartMonth int    `json:"financial_year_start_month"`
	DefaultCurrency         string `json:"default_currency"`
	Timezone                string `json:"timezone"`
	DateFormat              string `json:"date_format"`
	TimeFormat              string `json:"time_format"`
}

func (h *BusinessHandler) UpsertSettings(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBusinessManage) {
		return
	}
	// Start from the stored values so a tab that sends only its own fields (Company or Currency
	// & Time) never blanks the others: JSON decoding only overwrites the keys present.
	var b settingsBody
	if cur, err := h.svc.GetSettings(r.Context(), scope.TenantID); err == nil && cur != nil {
		b = settingsBody{LegalName: cur.LegalName, KRAPin: cur.KraPin, NSSFEmployerNo: cur.NssfEmployerNo,
			SHIFEmployerNo: cur.ShifEmployerNo, ContactEmail: cur.ContactEmail, ContactPhone: cur.ContactPhone,
			PostalAddress: cur.PostalAddress, PhysicalAddress: cur.PhysicalAddress,
			FinancialYearStartMonth: cur.FinancialYearStartMonth, DefaultCurrency: cur.DefaultCurrency,
			Timezone: cur.Timezone, DateFormat: cur.DateFormat, TimeFormat: cur.TimeFormat}
	}
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpsertSettings(r.Context(), scope.TenantID, business.SettingsInput{
		LegalName: b.LegalName, KRAPin: b.KRAPin, NSSFEmployerNo: b.NSSFEmployerNo,
		SHIFEmployerNo: b.SHIFEmployerNo, ContactEmail: b.ContactEmail, ContactPhone: b.ContactPhone,
		PostalAddress: b.PostalAddress, PhysicalAddress: b.PhysicalAddress,
		FinancialYearStartMonth: b.FinancialYearStartMonth, DefaultCurrency: b.DefaultCurrency,
		Timezone: b.Timezone, DateFormat: b.DateFormat, TimeFormat: b.TimeFormat,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "save_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"settings": row})
}

func (h *BusinessHandler) ListSequences(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBusinessView) {
		return
	}
	rows, err := h.svc.ListSequences(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list sequences")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type prefixBody struct {
	DocType    string `json:"doc_type"`
	Prefix     string `json:"prefix"`
	Separator  string `json:"separator"`
	DateFormat string `json:"date_format"`
	Padding    int    `json:"padding"`
	ResetFreq  string `json:"reset_freq"`
}

func (h *BusinessHandler) UpsertSequence(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBusinessManage) {
		return
	}
	var b prefixBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpsertSequenceConfig(r.Context(), scope.TenantID, business.PrefixInput{
		DocType: b.DocType, Prefix: b.Prefix, Separator: b.Separator,
		DateFormat: b.DateFormat, Padding: b.Padding, ResetFreq: b.ResetFreq,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "save_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *BusinessHandler) NextNumber(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBusinessManage) {
		return
	}
	docType := chi.URLParam(r, "docType")
	num, err := h.svc.NextNumber(r.Context(), scope.TenantID, docType)
	if err != nil {
		writeError(w, http.StatusBadRequest, "sequence_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"doc_type": docType, "number": num})
}
