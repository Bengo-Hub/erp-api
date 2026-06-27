package handlers

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
	"github.com/Bengo-Hub/erp-api/internal/platform/lookups"
	"github.com/Bengo-Hub/erp-api/internal/platform/media"
)

// Payroll RBAC permission codes.
const (
	permPayrollView     = "hrm.payroll.view"
	permPayrollManage   = "hrm.payroll.manage"
	permPayrollProcess  = "hrm.payroll.process"
	permPayrollDisburse = "hrm.payroll.disburse" // segregation of duties: paying out is distinct from processing
)

// PayrollHandler serves /api/v1/hrm/payroll/* (runs, preview, process, payslips,
// advances, loss-damages, claims) and the disburse command. Reuses the payroll
// engine service + Disburser.
type PayrollHandler struct {
	log       *zap.Logger
	svc       *payroll.Service
	disburser *payroll.Disburser
	media     *media.Store
	lookups   *lookups.Client
}

func NewPayrollHandler(log *zap.Logger, svc *payroll.Service, disburser *payroll.Disburser) *PayrollHandler {
	return &PayrollHandler{log: log.Named("hrm.payroll"), svc: svc, disburser: disburser}
}

// WithMedia wires the media store so claim attachments can be uploaded. Optional.
func (h *PayrollHandler) WithMedia(m *media.Store) *PayrollHandler { h.media = m; return h }

// WithLookups wires the cross-service cost-allocation lookup client (projects/cost-centers).
// Optional — when nil the lookup endpoints fall back to ERP-derived distinct values.
func (h *PayrollHandler) WithLookups(l *lookups.Client) *PayrollHandler { h.lookups = l; return h }

func (h *PayrollHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/payroll", func(pr chi.Router) {
		// Runs / payslips collection (erp-ui calls /hrm/payroll/payroll/...).
		pr.Get("/payroll", h.ListPayslips)
		pr.Post("/payroll", h.Command) // command dispatcher (disburse/...)
		pr.Get("/payroll/employees", h.PayrollEmployees)
		pr.Get("/payroll/{id}", h.GetPayslip)
		pr.Delete("/payroll/{id}", h.DeletePayslip)

		// Calculation / processing.
		pr.Post("/calculation-preview", h.Preview)
		pr.Post("/process-with-formulas", h.Process)
		pr.Get("/task_status", h.TaskStatus)
		pr.Post("/email-payslips", h.EmailPayslips)

		// Cost-allocation lookups (S2S proxy to projects-service + treasury, JWT-forwarded).
		pr.Get("/lookups/projects", h.LookupProjects)
		pr.Get("/lookups/cost-centers", h.LookupCostCenters)

		// Advances.
		pr.Get("/advances", h.ListAdvances)
		pr.Post("/advances", h.CreateAdvance)
		pr.Put("/advances/{id}", h.UpdateAdvance)
		pr.Post("/advances/{id}/approve", h.ApproveAdvance)
		pr.Post("/advances/{id}/disapprove", h.DisapproveAdvance)
		pr.Delete("/advances/{id}", h.DeleteAdvance)

		// Loss & damages.
		pr.Get("/losses-damages", h.ListLossDamages)
		pr.Post("/losses-damages", h.CreateLossDamage)
		pr.Put("/losses-damages/{id}", h.UpdateLossDamage)
		pr.Post("/losses-damages/{id}/approve", h.ApproveLossDamage)
		pr.Post("/losses-damages/{id}/disapprove", h.DisapproveLossDamage)
		pr.Delete("/losses-damages/{id}", h.DeleteLossDamage)

		// Claims.
		pr.Get("/claims", h.ListClaims)
		pr.Get("/claims/{id}", h.GetClaim)
		pr.Post("/claims", h.CreateClaim)
		pr.Put("/claims/{id}", h.UpdateClaim)
		pr.Post("/claims/{id}/approve", h.ApproveClaim)
		pr.Delete("/claims/{id}", h.DeleteClaim)
		// Attachment upload (media store) + conditional line tables.
		pr.Post("/claims/{id}/attachment", h.UploadClaimAttachment)
		pr.Get("/claims/{id}/items", h.ListClaimItems)
		pr.Post("/claims/{id}/items", h.CreateClaimItem)
		pr.Delete("/claims/{id}/items/{itemId}", h.DeleteClaimItem)
		pr.Get("/claims/{id}/mileage-routes", h.ListMileageRoutes)
		pr.Post("/claims/{id}/mileage-routes", h.CreateMileageRoute)
		pr.Delete("/claims/{id}/mileage-routes/{routeId}", h.DeleteMileageRoute)

		// Casual / subcontracted labour register.
		pr.Get("/casual-labor", h.ListCasualLabor)
		pr.Post("/casual-labor", h.CreateCasualLabor)
		pr.Put("/casual-labor/{id}", h.UpdateCasualLabor)
		pr.Post("/casual-labor/{id}/approve", h.ApproveCasualLabor)
		pr.Delete("/casual-labor/{id}", h.DeleteCasualLabor)
	})
}

// parsePeriod resolves a payroll period (first-of-month, UTC) from a "YYYY-MM",
// "YYYY-MM-DD" or RFC3339 string. Returns zero time on empty.
func parsePeriod(s string) (time.Time, bool) {
	if s == "" {
		return time.Time{}, false
	}
	if t, err := time.Parse("2006-01", s); err == nil {
		return time.Date(t.Year(), t.Month(), 1, 0, 0, 0, 0, time.UTC), true
	}
	if t, err := parseDate(s); err == nil {
		return time.Date(t.Year(), t.Month(), 1, 0, 0, 0, 0, time.UTC), true
	}
	return time.Time{}, false
}

// ---- Payslip views ----

type payslipView struct {
	ID              uuid.UUID `json:"id"`
	Employee        uuid.UUID `json:"employee"`
	EmployeeID      uuid.UUID `json:"employee_id"`
	EmployeeName    string    `json:"employee_name,omitempty"`
	EmployeeNumber  string    `json:"employee_number,omitempty"`
	PaymentPeriod   string    `json:"payment_period,omitempty"`
	Period          string    `json:"period,omitempty"`
	GrossPay        string    `json:"gross_pay"`
	BasicSalary     string    `json:"basic_salary"`
	TotalEarnings   string    `json:"total_earnings"`
	TotalDeductions string    `json:"total_deductions"`
	Paye            string    `json:"paye"`
	Nssf            string    `json:"nssf"`
	Shif            string    `json:"shif"`
	HousingLevy     string    `json:"housing_levy"`
	NetPay          string    `json:"net_pay"`
	Status          string    `json:"status,omitempty"`
	PaymentStatus   string    `json:"payment_status,omitempty"`
	Currency        string    `json:"currency"`
	BatchRef        string    `json:"batch_ref,omitempty"`
	CreatedAt       string    `json:"created_at,omitempty"`
	// Itemised lines (populated from payslip_line for new runs; empty for old payslips).
	Earnings   []payslipLineView `json:"earnings,omitempty"`
	Deductions []payslipLineView `json:"deductions,omitempty"`
}

type payslipLineView struct {
	Label  string `json:"label"`
	Name   string `json:"name"`
	Amount string `json:"amount"`
}

func (h *PayrollHandler) payslipView(ctx context.Context, tenantID uuid.UUID, ps *ent.Payslip) payslipView {
	// Single source of truth for the earnings/deductions/net figures (shared with the
	// PDF document adapter so the JSON view and the payslip PDF never drift). When the payslip
	// has itemised lines (new runs), they replace the lumped earnings/statutory rows.
	lines, _ := h.svc.LoadPayslipLines(ctx, tenantID, ps.ID)
	b := payroll.BuildPayslipBreakdownWithLines(ps, lines)
	v := payslipView{
		ID:              ps.ID,
		Employee:        ps.EmployeeID,
		EmployeeID:      ps.EmployeeID,
		GrossPay:        b.GrossPay.StringFixed(2),
		BasicSalary:     b.BasicSalary.StringFixed(2),
		TotalEarnings:   b.TotalEarnings.StringFixed(2),
		TotalDeductions: b.TotalDeductions.StringFixed(2),
		Paye:            b.PAYE.StringFixed(2),
		Nssf:            b.NSSF.StringFixed(2),
		Shif:            b.SHIF.StringFixed(2),
		HousingLevy:     b.HousingLevy.StringFixed(2),
		NetPay:          b.NetPay.StringFixed(2),
		Status:          ps.ApprovalStatus,
		Currency:        "KES",
		CreatedAt:       ps.CreatedAt.Format(time.RFC3339),
	}
	for _, e := range b.Earnings {
		v.Earnings = append(v.Earnings, payslipLineView{Label: e.Label, Name: e.Label, Amount: e.Amount.StringFixed(2)})
	}
	for _, d := range b.Deductions {
		v.Deductions = append(v.Deductions, payslipLineView{Label: d.Label, Name: d.Label, Amount: d.Amount.StringFixed(2)})
	}
	if ps.Published {
		v.PaymentStatus = "paid"
	} else {
		v.PaymentStatus = "pending"
	}
	if ps.PaymentPeriod != nil {
		v.PaymentPeriod = ps.PaymentPeriod.Format("2006-01")
		v.Period = v.PaymentPeriod
	}
	if ps.BatchRef != nil {
		v.BatchRef = *ps.BatchRef
	}
	v.EmployeeName, v.EmployeeNumber = h.svc.EmployeeLabel(ctx, tenantID, ps.EmployeeID)
	return v
}

func (h *PayrollHandler) ListPayslips(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	// ESS: ?mine=true is self-service (caller's own payslips only) and bypasses the
	// manager payroll-view permission; otherwise the manager perm is required.
	mine := r.URL.Query().Get("mine") == "true"
	if !mine && !requirePermission(w, scope, permPayrollView) {
		return
	}
	var period *time.Time
	if p, has := parsePeriod(r.URL.Query().Get("payment_period")); has {
		period = &p
	}
	empID := selfOrParamEmployeeID(r, scope)
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListPayslips(r.Context(), scope.TenantID, period, empID, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list payslips")
		return
	}
	out := make([]payslipView, 0, len(rows))
	for _, ps := range rows {
		out = append(out, h.payslipView(r.Context(), scope.TenantID, ps))
	}
	writePaginated(w, out, total, p)
}

func (h *PayrollHandler) GetPayslip(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	ps, err := h.svc.GetPayslip(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "payslip not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch payslip")
		return
	}
	writeJSON(w, http.StatusOK, h.payslipView(r.Context(), scope.TenantID, ps))
}

func (h *PayrollHandler) DeletePayslip(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.SoftDeletePayslip(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// PayrollEmployees lists employees eligible for a payroll run (active, non-terminated).
// Returns the same employee rows the run would select, with basic salary when available.
func (h *PayrollHandler) PayrollEmployees(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	rp := payroll.RunParams{
		TenantID: scope.TenantID,
		OutletID: scope.OutletID,
		Period:   firstOfThisMonth(),
		Persist:  false,
	}
	if v := r.URL.Query().Get("department_id"); v != "" {
		if id, err := uuid.Parse(v); err == nil {
			rp.DepartmentID = id
		}
	}
	if v := r.URL.Query().Get("region_id"); v != "" {
		if id, err := uuid.Parse(v); err == nil {
			rp.RegionID = id
		}
	}
	if v := r.URL.Query().Get("project_id"); v != "" {
		if id, err := uuid.Parse(v); err == nil {
			rp.ProjectID = id
		}
	}
	res, err := h.svc.Run(r.Context(), rp)
	if err != nil {
		// Config/data not ready is not fatal for a listing — return empty.
		h.log.Warn("payroll employees preview", zap.Error(err))
		writePagedSlice(w, []map[string]any{}, pagination.Parse(r))
		return
	}
	out := make([]map[string]any, 0, len(res))
	for _, line := range res {
		name, number := h.svc.EmployeeLabel(r.Context(), scope.TenantID, line.EmployeeID)
		out = append(out, map[string]any{
			"id":              line.EmployeeID,
			"employee":        line.EmployeeID,
			"employee_id":     line.EmployeeID,
			"employee_name":   name,
			"employee_number": number,
			"basic_salary":    line.Result.GrossPay.StringFixed(2),
			"net_pay":         line.Result.NetPay.StringFixed(2),
		})
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

func firstOfThisMonth() time.Time {
	now := time.Now().UTC()
	return time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC)
}

// ---- Preview / process ----

type processBody struct {
	PaymentPeriod  string   `json:"payment_period"`
	FromDate       string   `json:"from_date"`
	ToDate         string   `json:"to_date"`
	EmploymentType string   `json:"employment_type"`
	OutletID       string   `json:"outlet_id"`
	DepartmentID   string   `json:"department_id"`
	RegionID       string   `json:"region_id"`
	ProjectID      string   `json:"project_id"`
	EmployeeIDs    []string `json:"employee_ids"`
}

func (b processBody) period() (time.Time, bool) {
	if p, ok := parsePeriod(b.PaymentPeriod); ok {
		return p, true
	}
	return parsePeriod(b.FromDate)
}

func (b processBody) employeeUUIDs() []uuid.UUID {
	ids := make([]uuid.UUID, 0, len(b.EmployeeIDs))
	for _, s := range b.EmployeeIDs {
		if id, err := uuid.Parse(s); err == nil {
			ids = append(ids, id)
		}
	}
	return ids
}

func (h *PayrollHandler) runParams(scope RequestScope, b processBody, persist bool) (payroll.RunParams, bool) {
	period, ok := b.period()
	if !ok {
		return payroll.RunParams{}, false
	}
	rp := payroll.RunParams{
		TenantID:    scope.TenantID,
		OutletID:    scope.OutletID,
		Period:      period,
		EmployeeIDs: b.employeeUUIDs(),
		CreatedBy:   scope.UserID,
		Persist:     persist,
	}
	if b.OutletID != "" {
		if oid, err := uuid.Parse(b.OutletID); err == nil {
			rp.OutletID = oid
		}
	}
	if did, err := uuid.Parse(b.DepartmentID); err == nil {
		rp.DepartmentID = did
	}
	if rid, err := uuid.Parse(b.RegionID); err == nil {
		rp.RegionID = rid
	}
	if pid, err := uuid.Parse(b.ProjectID); err == nil {
		rp.ProjectID = pid
	}
	return rp, true
}

func (h *PayrollHandler) Preview(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollProcess) {
		return
	}
	var body processBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	rp, ok := h.runParams(scope, body, false)
	if !ok {
		writeError(w, http.StatusBadRequest, "bad_request", "payment_period or from_date is required")
		return
	}
	res, err := h.svc.Run(r.Context(), rp)
	if err != nil {
		writeError(w, http.StatusBadRequest, "preview_failed", err.Error())
		return
	}
	rows := make([]map[string]any, 0, len(res))
	for _, line := range res {
		name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, line.EmployeeID)
		res := line.Result
		nssf := res.NSSFEmployeeTier1.Add(res.NSSFEmployeeTier2)
		rows = append(rows, map[string]any{
			"employee":         line.EmployeeID,
			"employee_id":      line.EmployeeID,
			"employee_name":    name,
			"gross_pay":        res.GrossPay.StringFixed(2),
			"paye":             res.PAYE.StringFixed(2),
			"nssf":             nssf.StringFixed(2),
			"shif":             res.SHIFOrNHIF.StringFixed(2),
			"housing_levy":     res.HousingLevy.StringFixed(2),
			"total_deductions": res.GrossPay.Sub(res.NetPay).StringFixed(2),
			"net_pay":          res.NetPay.StringFixed(2),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": rows, "data": rows})
}

func (h *PayrollHandler) Process(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollProcess) {
		return
	}
	var body processBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	rp, ok := h.runParams(scope, body, true)
	if !ok {
		writeError(w, http.StatusBadRequest, "bad_request", "payment_period or from_date is required")
		return
	}
	res, err := h.svc.Run(r.Context(), rp)
	if err != nil {
		writeError(w, http.StatusBadRequest, "process_failed", err.Error())
		return
	}
	// Synchronous run (no Celery): return a completed task envelope so the UI poller
	// resolves immediately.
	writeJSON(w, http.StatusOK, map[string]any{
		"task_id": rp.Period.Format("2006-01"),
		"status":  "completed",
		"message": "payroll processed",
		"count":   len(res),
	})
}

// TaskStatus reports a completed status (payroll runs synchronously in erp-api;
// there is no async task queue). Kept so the erp-ui poller resolves.
func (h *PayrollHandler) TaskStatus(w http.ResponseWriter, r *http.Request) {
	if _, ok := scopeFromRequest(w, r); !ok {
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"state":    "SUCCESS",
		"status":   "completed",
		"progress": 100,
	})
}

// EmailPayslips acknowledges the request. Payslip emailing is delegated to
// notifications-service via the outbox elsewhere; this endpoint exists so the UI
// action resolves without a 404.
func (h *PayrollHandler) EmailPayslips(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "queued"})
}

// ---- Command dispatcher (disburse) ----

type commandBody struct {
	Command       string `json:"command"`
	PaymentPeriod string `json:"payment_period"`
	FromDate      string `json:"from_date"`
	ToDate        string `json:"to_date"`
	OutletID      string `json:"outlet_id"`
}

func (h *PayrollHandler) Command(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	var body commandBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	switch body.Command {
	case "disburse":
		// Paying out is a segregation-of-duties step distinct from processing.
		if !requirePermission(w, scope, permPayrollDisburse) {
			return
		}
		h.disburse(w, r, scope, body)
	case "reverse":
		if !requirePermission(w, scope, permPayrollDisburse) {
			return
		}
		h.reverse(w, r, scope, body)
	case "approve":
		if !requirePermission(w, scope, permPayrollManage) {
			return
		}
		h.setApproval(w, r, scope, body, "approved")
	case "reject":
		if !requirePermission(w, scope, permPayrollManage) {
			return
		}
		h.setApproval(w, r, scope, body, "rejected")
	default:
		writeError(w, http.StatusBadRequest, "bad_request", "unknown command")
	}
}

// setApproval transitions the period's payslips to approved/rejected — the explicit review step
// between process and disburse (the disburser then only pays out approved+complete payslips).
func (h *PayrollHandler) setApproval(w http.ResponseWriter, r *http.Request, scope RequestScope, body commandBody, status string) {
	period := body.PaymentPeriod
	if period == "" {
		period = body.FromDate
	}
	p, ok := parsePeriod(period)
	if !ok {
		writeError(w, http.StatusBadRequest, "bad_request", "payment_period is required")
		return
	}
	var outlet *uuid.UUID
	if body.OutletID != "" {
		if oid, err := uuid.Parse(body.OutletID); err == nil {
			outlet = &oid
		}
	} else if scope.OutletID != uuid.Nil {
		outlet = &scope.OutletID
	}
	n, err := h.svc.SetPayslipsApproval(r.Context(), scope.TenantID, p, outlet, status)
	if err != nil {
		writeError(w, http.StatusBadRequest, "approval_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": status, "count": n, "payment_period": p.Format("2006-01")})
}

// reverse reverses a disbursed payroll batch (emits erp.payroll.reversed for treasury GL reversal).
func (h *PayrollHandler) reverse(w http.ResponseWriter, r *http.Request, scope RequestScope, body commandBody) {
	if h.disburser == nil {
		writeError(w, http.StatusServiceUnavailable, "unavailable", "disbursement not configured")
		return
	}
	period := body.PaymentPeriod
	if period == "" {
		period = body.FromDate
	}
	p, ok := parsePeriod(period)
	if !ok {
		writeError(w, http.StatusBadRequest, "bad_request", "payment_period is required")
		return
	}
	dp := payroll.DisburseParams{TenantID: scope.TenantID, OutletID: scope.OutletID, Period: p, IdemKey: r.Header.Get("Idempotency-Key")}
	if body.OutletID != "" {
		if oid, err := uuid.Parse(body.OutletID); err == nil {
			dp.OutletID = oid
		}
	}
	res, err := h.disburser.Reverse(r.Context(), dp)
	if err != nil {
		writeError(w, http.StatusBadRequest, "reverse_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, res)
}

func (h *PayrollHandler) disburse(w http.ResponseWriter, r *http.Request, scope RequestScope, body commandBody) {
	if h.disburser == nil {
		writeError(w, http.StatusServiceUnavailable, "unavailable", "disbursement not configured")
		return
	}
	period := body.PaymentPeriod
	if period == "" {
		period = body.FromDate
	}
	p, ok := parsePeriod(period)
	if !ok {
		writeError(w, http.StatusBadRequest, "bad_request", "payment_period is required")
		return
	}
	dp := payroll.DisburseParams{
		TenantID: scope.TenantID,
		OutletID: scope.OutletID,
		Period:   p,
		IdemKey:  r.Header.Get("Idempotency-Key"),
	}
	if body.OutletID != "" {
		if oid, err := uuid.Parse(body.OutletID); err == nil {
			dp.OutletID = oid
		}
	}
	res, err := h.disburser.Disburse(r.Context(), dp)
	if err != nil {
		writeError(w, http.StatusBadRequest, "disburse_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, res)
}

// ---- Advances / loss-damages / claims ----

type recoverableBody struct {
	Employee         string `json:"employee"`
	EmployeeID       string `json:"employee_id"`
	Amount           string `json:"amount"`
	Description      string `json:"description"`
	Reason           string `json:"reason"`
	Date             string `json:"date"`
	IsActive         *bool  `json:"is_active"`
	NoOfInstallments int    `json:"no_of_installments"`
}

func (b recoverableBody) toInput() (payroll.RecoverableInput, error) {
	in := payroll.RecoverableInput{IsActive: b.IsActive == nil || *b.IsActive, NoOfInstallments: b.NoOfInstallments}
	empStr := b.EmployeeID
	if empStr == "" {
		empStr = b.Employee
	}
	if empStr != "" {
		eid, err := uuid.Parse(empStr)
		if err != nil {
			return in, errBadEmployee
		}
		in.EmployeeID = eid
	}
	if b.Amount != "" {
		amt, err := decimal.NewFromString(b.Amount)
		if err != nil {
			return in, errBadAmount
		}
		in.Amount = amt
	}
	in.Description = b.Description
	if in.Description == "" {
		in.Description = b.Reason
	}
	if b.Date != "" {
		if d, err := parseDate(b.Date); err == nil {
			in.IssueDate = &d
		}
	}
	return in, nil
}

var errBadAmount = contractError{"invalid amount (must be a decimal string)"}

// recoverableStatus maps the approved/is_active flag pair to a tab status string.
func recoverableStatus(approved, isActive bool) string {
	switch {
	case approved && isActive:
		return "scheduled"
	case approved:
		return "approved"
	case isActive:
		return "pending"
	default:
		return "disapproved"
	}
}

func advanceView(a *ent.Advance, name string) map[string]any {
	v := map[string]any{
		"id":              a.ID,
		"employee":        a.EmployeeID,
		"employee_id":     a.EmployeeID,
		"employee_name":   name,
		"amount":          a.AmountIssued.StringFixed(2),
		"amount_repaid":   a.AmountRepaid.StringFixed(2),
		"approved":        a.Approved,
		"is_active":       a.IsActive,
		"status":          recoverableStatus(a.Approved, a.IsActive),
		"repay_option_id": a.RepayOptionID,
		"created_at":      a.CreatedAt.Format(time.RFC3339),
	}
	if a.IssueDate != nil {
		v["date"] = a.IssueDate.Format("2006-01-02")
	}
	return v
}

func (h *PayrollHandler) ListAdvances(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	status := r.URL.Query().Get("status")
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListAdvances(r.Context(), scope.TenantID, empID, status, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list advances")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, a := range rows {
		name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, a.EmployeeID)
		out = append(out, advanceView(a, name))
	}
	writePaginated(w, out, total, p)
}

func (h *PayrollHandler) CreateAdvance(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	in, ok := h.decodeRecoverable(w, r)
	if !ok {
		return
	}
	a, err := h.svc.CreateAdvance(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, a.EmployeeID)
	writeJSON(w, http.StatusCreated, advanceView(a, name))
}

func (h *PayrollHandler) UpdateAdvance(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	in, ok := h.decodeRecoverable(w, r)
	if !ok {
		return
	}
	a, err := h.svc.UpdateAdvance(r.Context(), scope.TenantID, id, in)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "advance not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, a.EmployeeID)
	writeJSON(w, http.StatusOK, advanceView(a, name))
}

func (h *PayrollHandler) DeleteAdvance(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteAdvance(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func lossDamageView(l *ent.LossAndDamage, name string) map[string]any {
	v := map[string]any{
		"id":              l.ID,
		"employee":        l.EmployeeID,
		"employee_id":     l.EmployeeID,
		"employee_name":   name,
		"amount":          l.DamageAmount.StringFixed(2),
		"amount_repaid":   l.AmountRepaid.StringFixed(2),
		"approved":        l.Approved,
		"is_active":       l.IsActive,
		"status":          recoverableStatus(l.Approved, l.IsActive),
		"repay_option_id": l.RepayOptionID,
		"created_at":      l.CreatedAt.Format(time.RFC3339),
	}
	if l.Description != nil {
		v["description"] = *l.Description
	}
	if l.IssueDate != nil {
		v["date"] = l.IssueDate.Format("2006-01-02")
	}
	return v
}

func (h *PayrollHandler) ListLossDamages(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	status := r.URL.Query().Get("status")
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListLossDamages(r.Context(), scope.TenantID, empID, status, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list loss-damages")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, l := range rows {
		name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, l.EmployeeID)
		out = append(out, lossDamageView(l, name))
	}
	writePaginated(w, out, total, p)
}

func (h *PayrollHandler) CreateLossDamage(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	in, ok := h.decodeRecoverable(w, r)
	if !ok {
		return
	}
	l, err := h.svc.CreateLossDamage(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, l.EmployeeID)
	writeJSON(w, http.StatusCreated, lossDamageView(l, name))
}

func (h *PayrollHandler) UpdateLossDamage(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	in, ok := h.decodeRecoverable(w, r)
	if !ok {
		return
	}
	l, err := h.svc.UpdateLossDamage(r.Context(), scope.TenantID, id, in)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "loss-damage not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, l.EmployeeID)
	writeJSON(w, http.StatusOK, lossDamageView(l, name))
}

func (h *PayrollHandler) DeleteLossDamage(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteLossDamage(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *PayrollHandler) decodeRecoverable(w http.ResponseWriter, r *http.Request) (payroll.RecoverableInput, bool) {
	var body recoverableBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return payroll.RecoverableInput{}, false
	}
	in, err := body.toInput()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return payroll.RecoverableInput{}, false
	}
	return in, true
}

// ---- Claims ----

type claimBody struct {
	Employee     string `json:"employee"`
	EmployeeID   string `json:"employee_id"`
	Amount       string `json:"amount"`
	ClaimType    string `json:"claim_type"`
	Category     string `json:"category"`
	Date         string `json:"date"`
	ProjectID    string `json:"project_id"`
	CostCenterID string `json:"cost_center_id"`
	Taxable      *bool  `json:"taxable"`
}

func (b claimBody) toInput() (payroll.ClaimInput, error) {
	in := payroll.ClaimInput{}
	empStr := b.EmployeeID
	if empStr == "" {
		empStr = b.Employee
	}
	if empStr != "" {
		eid, err := uuid.Parse(empStr)
		if err != nil {
			return in, errBadEmployee
		}
		in.EmployeeID = eid
	}
	if b.Amount != "" {
		amt, err := decimal.NewFromString(b.Amount)
		if err != nil {
			return in, errBadAmount
		}
		in.Amount = amt
	}
	in.Category = b.Category
	in.ClaimType = b.ClaimType
	if in.Category == "" {
		in.Category = b.ClaimType
	}
	in.Taxable = b.Taxable
	if b.ProjectID != "" {
		if pid, err := uuid.Parse(b.ProjectID); err == nil {
			in.ProjectID = &pid
		}
	}
	if b.CostCenterID != "" {
		if cid, err := uuid.Parse(b.CostCenterID); err == nil {
			in.CostCenterID = &cid
		}
	}
	if b.Date != "" {
		if d, err := parseDate(b.Date); err == nil {
			in.ApplicationDate = &d
		}
	}
	return in, nil
}

func claimView(c *ent.ExpenseClaim, name string) map[string]any {
	v := map[string]any{
		"id":            c.ID,
		"employee":      c.EmployeeID,
		"employee_id":   c.EmployeeID,
		"employee_name": name,
		"amount":        c.Amount.StringFixed(2),
		"claim_type":    c.ClaimType,
		"category":      c.Category,
		"taxable":       c.Taxable,
		"approved":      c.Approved,
		"status":        claimStatus(c),
		"is_paid":       c.IsPaid,
		"created_at":    c.CreatedAt.Format(time.RFC3339),
	}
	if c.ProjectID != nil {
		v["project_id"] = c.ProjectID
	}
	if c.CostCenterID != nil {
		v["cost_center_id"] = c.CostCenterID
	}
	if c.ApplicationDate != nil {
		v["date"] = c.ApplicationDate.Format("2006-01-02")
	}
	if c.AttachmentURL != nil {
		v["attachment_url"] = *c.AttachmentURL
	}
	return v
}

func claimStatus(c *ent.ExpenseClaim) string {
	switch {
	case c.IsPaid:
		return "paid"
	case c.Approved:
		return "approved"
	default:
		return "pending"
	}
}

func (h *PayrollHandler) ListClaims(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListClaims(r.Context(), scope.TenantID, empID, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list claims")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, c := range rows {
		name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, c.EmployeeID)
		out = append(out, claimView(c, name))
	}
	writePaginated(w, out, total, p)
}

func (h *PayrollHandler) GetClaim(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	c, err := h.svc.GetClaim(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "claim not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch claim")
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, c.EmployeeID)
	writeJSON(w, http.StatusOK, claimView(c, name))
}

// ---- Casual labour ----

type casualLaborBody struct {
	EngagedByEmployeeID string `json:"engaged_by_employee_id"`
	ProjectID           string `json:"project_id"`
	CostCenterID        string `json:"cost_center_id"`
	WorkerName          string `json:"worker_name"`
	WorkerIDNumber      string `json:"worker_id_number"`
	WorkerPhone         string `json:"worker_phone"`
	TaskDescription     string `json:"task_description"`
	Amount              string `json:"amount"`
	PaymentMethod       string `json:"payment_method"`
	ImprestAdvanceID    string `json:"imprest_advance_id"`
}

func (b casualLaborBody) toInput() payroll.CasualLaborInput {
	in := payroll.CasualLaborInput{
		WorkerName: b.WorkerName, WorkerIDNumber: b.WorkerIDNumber, WorkerPhone: b.WorkerPhone,
		TaskDescription: b.TaskDescription, PaymentMethod: b.PaymentMethod,
	}
	if b.Amount != "" {
		if amt, err := decimal.NewFromString(b.Amount); err == nil {
			in.Amount = amt
		}
	}
	if id, err := uuid.Parse(b.EngagedByEmployeeID); err == nil {
		in.EngagedByEmployeeID = &id
	}
	if id, err := uuid.Parse(b.ProjectID); err == nil {
		in.ProjectID = &id
	}
	if id, err := uuid.Parse(b.CostCenterID); err == nil {
		in.CostCenterID = &id
	}
	if id, err := uuid.Parse(b.ImprestAdvanceID); err == nil {
		in.ImprestAdvanceID = &id
	}
	return in
}

func casualLaborView(c *ent.CasualLaborRecord) map[string]any {
	v := map[string]any{
		"id": c.ID, "worker_name": c.WorkerName, "worker_id_number": c.WorkerIDNumber,
		"worker_phone": c.WorkerPhone, "task_description": c.TaskDescription,
		"amount": c.Amount.StringFixed(2), "payment_method": c.PaymentMethod,
		"status": string(c.Status), "created_at": c.CreatedAt.Format(time.RFC3339),
	}
	if c.EngagedByEmployeeID != nil {
		v["engaged_by_employee_id"] = c.EngagedByEmployeeID
	}
	if c.ProjectID != nil {
		v["project_id"] = c.ProjectID
	}
	if c.CostCenterID != nil {
		v["cost_center_id"] = c.CostCenterID
	}
	if c.ImprestAdvanceID != nil {
		v["imprest_advance_id"] = c.ImprestAdvanceID
	}
	return v
}

func (h *PayrollHandler) ListCasualLabor(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListCasualLabor(r.Context(), scope.TenantID, nil, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list casual labour")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, c := range rows {
		out = append(out, casualLaborView(c))
	}
	writePaginated(w, out, total, p)
}

func (h *PayrollHandler) CreateCasualLabor(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var body casualLaborBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	c, err := h.svc.CreateCasualLabor(r.Context(), scope.TenantID, body.toInput())
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, casualLaborView(c))
}

func (h *PayrollHandler) UpdateCasualLabor(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body casualLaborBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	c, err := h.svc.UpdateCasualLabor(r.Context(), scope.TenantID, id, body.toInput())
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, casualLaborView(c))
}

func (h *PayrollHandler) ApproveCasualLabor(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	c, err := h.svc.ApproveCasualLabor(r.Context(), scope.TenantID, id, scope.UserID)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "record not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to approve")
		return
	}
	writeJSON(w, http.StatusOK, casualLaborView(c))
}

func (h *PayrollHandler) DeleteCasualLabor(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteCasualLabor(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusBadRequest, "delete_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
}

// ApproveClaim approves a claim and emits erp.expense_claim.approved for treasury GL posting.
func (h *PayrollHandler) ApproveClaim(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	c, err := h.svc.ApproveClaim(r.Context(), scope.TenantID, id, scope.UserID)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "claim not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to approve claim")
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, c.EmployeeID)
	writeJSON(w, http.StatusOK, claimView(c, name))
}

func (h *PayrollHandler) CreateClaim(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var body claimBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := body.toInput()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	c, err := h.svc.CreateClaim(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, c.EmployeeID)
	writeJSON(w, http.StatusCreated, claimView(c, name))
}

func (h *PayrollHandler) UpdateClaim(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body claimBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := body.toInput()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	c, err := h.svc.UpdateClaim(r.Context(), scope.TenantID, id, in)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "claim not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, c.EmployeeID)
	writeJSON(w, http.StatusOK, claimView(c, name))
}

func (h *PayrollHandler) DeleteClaim(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteClaim(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
