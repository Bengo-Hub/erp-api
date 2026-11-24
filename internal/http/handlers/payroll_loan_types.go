package handlers

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeloan"
	"github.com/Bengo-Hub/erp-api/internal/ent/loantype"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/ent/recoveryline"
)

// ---- Loan types (Settings, Payroll, Loans) ----

func loanTypeView(t *ent.LoanType) map[string]any {
	v := map[string]any{"id": t.ID, "title": t.Title, "name": t.Title, "is_active": t.IsActive}
	if t.AccountCode != nil {
		v["account_code"] = *t.AccountCode
	}
	return v
}

type loanTypeBody struct {
	Title       string `json:"title"`
	Name        string `json:"name"`
	AccountCode string `json:"account_code"`
	IsActive    *bool  `json:"is_active"`
}

func (b loanTypeBody) title() string {
	if t := strings.TrimSpace(b.Title); t != "" {
		return t
	}
	return strings.TrimSpace(b.Name)
}

func (h *PayrollSettingsHandler) ListLoanTypes(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	rows, err := h.orm.LoanType.Query().Where(loantype.TenantID(scope.TenantID)).
		Order(ent.Asc(loantype.FieldTitle)).All(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list loan types")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, t := range rows {
		out = append(out, loanTypeView(t))
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

func (h *PayrollSettingsHandler) CreateLoanType(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var b loanTypeBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil || b.title() == "" {
		writeError(w, http.StatusBadRequest, "bad_request", "title is required")
		return
	}
	c := h.orm.LoanType.Create().SetTenantID(scope.TenantID).SetTitle(b.title()).
		SetIsActive(b.IsActive == nil || *b.IsActive)
	if code := strings.TrimSpace(b.AccountCode); code != "" {
		c = c.SetAccountCode(code)
	}
	row, err := c.Save(r.Context())
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, loanTypeView(row))
}

func (h *PayrollSettingsHandler) UpdateLoanType(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b loanTypeBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	existing, err := h.orm.LoanType.Query().Where(loantype.ID(id), loantype.TenantID(scope.TenantID)).Only(r.Context())
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "loan type not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch loan type")
		return
	}
	u := existing.Update()
	if t := b.title(); t != "" {
		u = u.SetTitle(t)
	}
	if b.IsActive != nil {
		u = u.SetIsActive(*b.IsActive)
	}
	if code := strings.TrimSpace(b.AccountCode); code != "" {
		u = u.SetAccountCode(code)
	}
	row, err := u.Save(r.Context())
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, loanTypeView(row))
}

func (h *PayrollSettingsHandler) DeleteLoanType(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if used, uerr := h.orm.EmployeeLoan.Query().Where(employeeloan.TenantID(scope.TenantID), employeeloan.LoanTypeID(id)).Exist(r.Context()); uerr != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to check loans")
		return
	} else if used {
		writeError(w, http.StatusConflict, "loan_type_in_use", "loans were issued under this type; deactivate it instead")
		return
	}
	n, err := h.orm.LoanType.Delete().Where(loantype.ID(id), loantype.TenantID(scope.TenantID)).Exec(r.Context())
	if err != nil || n == 0 {
		writeError(w, http.StatusNotFound, "not_found", "loan type not found")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// LoanRecoveries lists the payroll recoveries of one employee loan, newest period first: the
// amount each payslip took and whether it has been written back to the loan balance (it is,
// once the payroll batch is posted).
func (h *PayrollSettingsHandler) LoanRecoveries(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	lines, err := h.orm.RecoveryLine.Query().Where(recoveryline.TenantID(scope.TenantID),
		recoveryline.RecoverableTypeEQ(recoveryline.RecoverableTypeLoan), recoveryline.RecoverableID(id)).
		Order(ent.Desc(recoveryline.FieldCreatedAt)).Limit(240).All(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list recoveries")
		return
	}
	ids := make([]uuid.UUID, 0, len(lines))
	for _, l := range lines {
		ids = append(ids, l.PayslipID)
	}
	periods := map[uuid.UUID]string{}
	if len(ids) > 0 {
		slips, perr := h.orm.Payslip.Query().Where(payslip.TenantID(scope.TenantID), payslip.IDIn(ids...)).
			Select(payslip.FieldID, payslip.FieldPaymentPeriod).All(r.Context())
		if perr != nil {
			writeError(w, http.StatusInternalServerError, "internal_error", "failed to load payslips")
			return
		}
		for _, s := range slips {
			if s.PaymentPeriod != nil {
				periods[s.ID] = s.PaymentPeriod.Format("2006-01")
			}
		}
	}
	out := make([]map[string]any, 0, len(lines))
	for _, l := range lines {
		out = append(out, map[string]any{
			"id": l.ID, "payslip_id": l.PayslipID, "payment_period": periods[l.PayslipID],
			"amount": l.Amount.StringFixed(2), "applied": l.Applied, "batch_ref": l.BatchRef,
			"created_at": l.CreatedAt.Format(time.RFC3339),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": out, "count": len(out)})
}
