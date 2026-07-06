package handlers

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeloan"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollcomponent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollrelief"
	"github.com/Bengo-Hub/erp-api/internal/ent/generalhrsettings"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// PayrollSettingsHandler serves /api/v1/hrm/payroll-settings/* (components, loans,
// formulas, relief, general HR settings). Reuses the payrollsettings service for
// formula resolution and direct tenant-scoped Ent access for the config tables.
type PayrollSettingsHandler struct {
	log *zap.Logger
	svc *payrollsettings.Service
	orm *ent.Client
}

func NewPayrollSettingsHandler(log *zap.Logger, svc *payrollsettings.Service, orm *ent.Client) *PayrollSettingsHandler {
	return &PayrollSettingsHandler{log: log.Named("hrm.payroll-settings"), svc: svc, orm: orm}
}

func (h *PayrollSettingsHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/payroll-settings", func(pr chi.Router) {
		pr.Get("/payroll-components", h.ListComponents)
		pr.Post("/payroll-components", h.CreateComponent)
		pr.Get("/payroll-components/{id}", h.GetComponent)
		pr.Put("/payroll-components/{id}", h.UpdateComponent)
		pr.Delete("/payroll-components/{id}", h.DeleteComponent)

		pr.Get("/loans", h.ListLoans)
		pr.Post("/loans", h.CreateLoan)
		pr.Get("/loans/{id}", h.GetLoan)
		pr.Put("/loans/{id}", h.UpdateLoan)
		pr.Delete("/loans/{id}", h.DeleteLoan)

		pr.Get("/formulas", h.ListFormulas)
		pr.Get("/formulas/relief-status", h.ReliefStatus)
		pr.Post("/formula-management", h.FormulaManagement)
		pr.Post("/formulas", h.CreateFormula)
		pr.Get("/formulas/{id}", h.GetFormula)
		pr.Put("/formulas/{id}", h.UpdateFormula)

		pr.Get("/general-hr-settings", h.GetGeneralHR)
		pr.Post("/general-hr-settings", h.UpsertGeneralHR)
		pr.Put("/general-hr-settings/{id}", h.UpsertGeneralHR)
	})
}

// ---- Components ----

func componentView(c *ent.PayrollComponent) map[string]any {
	v := map[string]any{
		"id":         c.ID,
		"name":       c.Title,
		"title":      c.Title,
		"category":   c.Category,
		"mode":       c.Mode,
		"is_active":  c.IsActive,
		"non_cash":   c.NonCash,
		"statutory":  c.Statutory,
		"checkoff":   c.Checkoff,
		// Default monetary config (employee + employer side) so the UI shows the rate/amount.
		"amount":              c.Amount.StringFixed(2),
		"percentage":          c.Percentage.StringFixed(2),
		"percent_of":          c.PercentOf,
		"employer_amount":     c.EmployerAmount.StringFixed(2),
		"employer_percentage": c.EmployerPercentage.StringFixed(2),
		"unit_type":           c.UnitType,
		"unit_rate":           c.UnitRate.StringFixed(2),
		"quantity":            c.Quantity.StringFixed(2),
		"deduction_phase":     c.DeductionPhase,
		"created_at":          c.CreatedAt.Format(time.RFC3339),
	}
	if c.Description != nil {
		v["description"] = *c.Description
	}
	if c.RegistrationNo != nil {
		v["registration_no"] = *c.RegistrationNo
	}
	if c.EffectiveFrom != nil {
		v["effective_from"] = c.EffectiveFrom.Format("2006-01-02")
	}
	if c.EffectiveTo != nil {
		v["effective_to"] = c.EffectiveTo.Format("2006-01-02")
	}
	if c.TaxableStatus != "" {
		v["is_taxable"] = c.TaxableStatus == "taxable"
	}
	return v
}

func (h *PayrollSettingsHandler) ListComponents(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	q := h.orm.PayrollComponent.Query().Where(payrollcomponent.TenantID(scope.TenantID))
	if cat := r.URL.Query().Get("category"); cat != "" {
		q = q.Where(payrollcomponent.Category(cat))
	}
	rows, err := q.Order(ent.Asc(payrollcomponent.FieldTitle)).All(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list components")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, c := range rows {
		out = append(out, componentView(c))
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

func (h *PayrollSettingsHandler) GetComponent(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	c, err := h.orm.PayrollComponent.Query().
		Where(payrollcomponent.ID(id), payrollcomponent.TenantID(scope.TenantID)).Only(r.Context())
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "component not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch component")
		return
	}
	writeJSON(w, http.StatusOK, componentView(c))
}

type componentBody struct {
	Name               string `json:"name"`
	Title              string `json:"title"`
	Category           string `json:"category"`
	Description        string `json:"description"`
	Mode               string `json:"mode"`
	IsActive           *bool  `json:"is_active"`
	IsTaxable          *bool  `json:"is_taxable"`
	NonCash            *bool  `json:"non_cash"`
	Checkoff           *bool  `json:"checkoff"`
	Amount             string `json:"amount"`
	Percentage         string `json:"percentage"`
	PercentOf          string `json:"percent_of"`
	EmployerAmount     string `json:"employer_amount"`
	EmployerPercentage string `json:"employer_percentage"`
	RegistrationNo     string `json:"registration_no"`
	UnitType           string `json:"unit_type"`
	UnitRate           string `json:"unit_rate"`
	Quantity           string `json:"quantity"`
	EffectiveFrom      string `json:"effective_from"`
	EffectiveTo        string `json:"effective_to"`
}

// applyComponentMoney sets the decimal/money + unit fields on a create/update builder from
// the request body. Shared by Create and Update so the two never drift. Each money field is
// only applied when the caller sent a value (empty string = leave default/unchanged).
func applyComponentMoney[B interface {
	SetAmount(decimal.Decimal) B
	SetPercentage(decimal.Decimal) B
	SetPercentOf(string) B
	SetEmployerAmount(decimal.Decimal) B
	SetEmployerPercentage(decimal.Decimal) B
	SetRegistrationNo(string) B
	SetUnitType(string) B
	SetUnitRate(decimal.Decimal) B
	SetQuantity(decimal.Decimal) B
	SetMode(string) B
}](c B, b componentBody) B {
	setDec := func(s string, set func(decimal.Decimal) B) {
		if s == "" {
			return
		}
		if d, err := decimal.NewFromString(s); err == nil {
			c = set(d)
		}
	}
	setDec(b.Amount, c.SetAmount)
	setDec(b.Percentage, c.SetPercentage)
	setDec(b.EmployerAmount, c.SetEmployerAmount)
	setDec(b.EmployerPercentage, c.SetEmployerPercentage)
	setDec(b.UnitRate, c.SetUnitRate)
	setDec(b.Quantity, c.SetQuantity)
	if b.PercentOf != "" {
		c = c.SetPercentOf(b.PercentOf)
	}
	if b.RegistrationNo != "" {
		c = c.SetRegistrationNo(b.RegistrationNo)
	}
	if b.UnitType != "" {
		c = c.SetUnitType(b.UnitType)
	}
	if b.Mode != "" {
		c = c.SetMode(b.Mode)
	}
	return c
}

func (b componentBody) title() string {
	if b.Name != "" {
		return b.Name
	}
	return b.Title
}

func (h *PayrollSettingsHandler) CreateComponent(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var b componentBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	if b.title() == "" {
		writeError(w, http.StatusBadRequest, "bad_request", "name is required")
		return
	}
	c := h.orm.PayrollComponent.Create().
		SetTenantID(scope.TenantID).
		SetTitle(b.title()).
		SetIsActive(b.IsActive == nil || *b.IsActive)
	if b.Category != "" {
		c = c.SetCategory(b.Category)
	}
	if b.Description != "" {
		c = c.SetDescription(b.Description)
	}
	if b.NonCash != nil {
		c = c.SetNonCash(*b.NonCash)
	}
	if b.Checkoff != nil {
		c = c.SetCheckoff(*b.Checkoff)
	}
	if b.IsTaxable != nil {
		if *b.IsTaxable {
			c = c.SetTaxableStatus("taxable")
		} else {
			c = c.SetTaxableStatus("nontaxable")
		}
	}
	c = applyComponentMoney(c, b)
	if d, e := parseDate(b.EffectiveFrom); e == nil {
		c = c.SetEffectiveFrom(d)
	}
	if d, e := parseDate(b.EffectiveTo); e == nil {
		c = c.SetEffectiveTo(d)
	}
	row, err := c.Save(r.Context())
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, componentView(row))
}

func (h *PayrollSettingsHandler) UpdateComponent(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	existing, err := h.orm.PayrollComponent.Query().
		Where(payrollcomponent.ID(id), payrollcomponent.TenantID(scope.TenantID)).Only(r.Context())
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "component not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch component")
		return
	}
	var b componentBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	u := existing.Update()
	if b.title() != "" {
		u = u.SetTitle(b.title())
	}
	if b.Category != "" {
		u = u.SetCategory(b.Category)
	}
	if b.Description != "" {
		u = u.SetDescription(b.Description)
	}
	if b.IsActive != nil {
		u = u.SetIsActive(*b.IsActive)
	}
	if b.NonCash != nil {
		u = u.SetNonCash(*b.NonCash)
	}
	if b.Checkoff != nil {
		u = u.SetCheckoff(*b.Checkoff)
	}
	if b.IsTaxable != nil {
		if *b.IsTaxable {
			u = u.SetTaxableStatus("taxable")
		} else {
			u = u.SetTaxableStatus("nontaxable")
		}
	}
	u = applyComponentMoney(u, b)
	if d, e := parseDate(b.EffectiveFrom); e == nil {
		u = u.SetEffectiveFrom(d)
	}
	if d, e := parseDate(b.EffectiveTo); e == nil {
		u = u.SetEffectiveTo(d)
	}
	row, err := u.Save(r.Context())
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, componentView(row))
}

func (h *PayrollSettingsHandler) DeleteComponent(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	n, err := h.orm.PayrollComponent.Delete().
		Where(payrollcomponent.ID(id), payrollcomponent.TenantID(scope.TenantID)).Exec(r.Context())
	if err != nil || n == 0 {
		writeError(w, http.StatusNotFound, "not_found", "component not found")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Loans (loan products configured per tenant via EmployeeLoan templates) ----

func loanView(l *ent.EmployeeLoan) map[string]any {
	v := map[string]any{
		"id":                  l.ID,
		"employee":            l.EmployeeID,
		"principal_amount":    l.PrincipalAmount.StringFixed(2),
		"amount_repaid":       l.AmountRepaid.StringFixed(2),
		"monthly_installment": l.MonthlyInstallment.StringFixed(2),
		"interest_rate":       l.InterestRate.String(),
		"is_active":           l.IsActive,
		"created_at":          l.CreatedAt.Format(time.RFC3339),
	}
	if l.StartDate != nil {
		v["start_date"] = l.StartDate.Format("2006-01-02")
	}
	if l.EndDate != nil {
		v["end_date"] = l.EndDate.Format("2006-01-02")
	}
	return v
}

func (h *PayrollSettingsHandler) ListLoans(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	q := h.orm.EmployeeLoan.Query().Where(employeeloan.TenantID(scope.TenantID))
	if empID := optionalUUIDParam(r, "employee_id"); empID != nil {
		q = q.Where(employeeloan.EmployeeID(*empID))
	}
	rows, err := q.Order(ent.Desc(employeeloan.FieldCreatedAt)).All(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list loans")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, l := range rows {
		out = append(out, loanView(l))
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

func (h *PayrollSettingsHandler) GetLoan(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	l, err := h.orm.EmployeeLoan.Query().
		Where(employeeloan.ID(id), employeeloan.TenantID(scope.TenantID)).Only(r.Context())
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "loan not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch loan")
		return
	}
	writeJSON(w, http.StatusOK, loanView(l))
}

type loanBody struct {
	Employee           string `json:"employee"`
	EmployeeID         string `json:"employee_id"`
	PrincipalAmount    string `json:"principal_amount"`
	MaxAmount          string `json:"max_amount"`
	MonthlyInstallment string `json:"monthly_installment"`
	InterestRate       string `json:"interest_rate"`
	IsActive           *bool  `json:"is_active"`
	StartDate          string `json:"start_date"`
	EndDate            string `json:"end_date"`
}

func (h *PayrollSettingsHandler) CreateLoan(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var b loanBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empStr := b.EmployeeID
	if empStr == "" {
		empStr = b.Employee
	}
	empID, err := uuid.Parse(empStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "employee is required")
		return
	}
	principalStr := b.PrincipalAmount
	if principalStr == "" {
		principalStr = b.MaxAmount
	}
	principal, err := parsePositiveDecimal(principalStr, "principal_amount")
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	install, err := parseRequiredDecimal(b.MonthlyInstallment, "monthly_installment")
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	// Interest rate is optional (0 = interest-free loan); only reject if present and invalid.
	rate, err := parseDecimalDefault(b.InterestRate)
	if err != nil || rate.IsNegative() {
		writeError(w, http.StatusBadRequest, "bad_request", "interest_rate must be a valid non-negative number")
		return
	}
	if derr := validateDateOrder(b.StartDate, b.EndDate); derr != nil {
		writeError(w, http.StatusBadRequest, "bad_request", derr.Error())
		return
	}
	c := h.orm.EmployeeLoan.Create().
		SetTenantID(scope.TenantID).
		SetEmployeeID(empID).
		SetPrincipalAmount(principal).
		SetMonthlyInstallment(install).
		SetInterestRate(rate).
		SetIsActive(b.IsActive == nil || *b.IsActive)
	if d, derr := parseDate(b.StartDate); derr == nil {
		c = c.SetStartDate(d)
	}
	if d, derr := parseDate(b.EndDate); derr == nil {
		c = c.SetEndDate(d)
	}
	row, err := c.Save(r.Context())
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, loanView(row))
}

func (h *PayrollSettingsHandler) UpdateLoan(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	existing, err := h.orm.EmployeeLoan.Query().
		Where(employeeloan.ID(id), employeeloan.TenantID(scope.TenantID)).Only(r.Context())
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "loan not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch loan")
		return
	}
	var b loanBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	u := existing.Update()
	if b.PrincipalAmount != "" {
		d, e := parsePositiveDecimal(b.PrincipalAmount, "principal_amount")
		if e != nil {
			writeError(w, http.StatusBadRequest, "bad_request", e.Error())
			return
		}
		u = u.SetPrincipalAmount(d)
	}
	if b.MonthlyInstallment != "" {
		d, e := parseRequiredDecimal(b.MonthlyInstallment, "monthly_installment")
		if e != nil {
			writeError(w, http.StatusBadRequest, "bad_request", e.Error())
			return
		}
		u = u.SetMonthlyInstallment(d)
	}
	if b.InterestRate != "" {
		d, e := parseRequiredDecimal(b.InterestRate, "interest_rate")
		if e != nil {
			writeError(w, http.StatusBadRequest, "bad_request", e.Error())
			return
		}
		u = u.SetInterestRate(d)
	}
	if derr := validateDateOrder(b.StartDate, b.EndDate); derr != nil {
		writeError(w, http.StatusBadRequest, "bad_request", derr.Error())
		return
	}
	if b.IsActive != nil {
		u = u.SetIsActive(*b.IsActive)
	}
	if d, derr := parseDate(b.StartDate); derr == nil {
		u = u.SetStartDate(d)
	}
	if d, derr := parseDate(b.EndDate); derr == nil {
		u = u.SetEndDate(d)
	}
	row, err := u.Save(r.Context())
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, loanView(row))
}

func (h *PayrollSettingsHandler) DeleteLoan(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	n, err := h.orm.EmployeeLoan.Delete().
		Where(employeeloan.ID(id), employeeloan.TenantID(scope.TenantID)).Exec(r.Context())
	if err != nil || n == 0 {
		writeError(w, http.StatusNotFound, "not_found", "loan not found")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Formulas (read via the settings service) ----

func formulaView(f *ent.PayrollFormula) map[string]any {
	v := map[string]any{
		"id":         f.ID,
		"name":       f.Title,
		"title":      f.Title,
		"type":       f.Type,
		"category":   f.Category,
		"is_current": f.IsCurrent,
		"version":    f.Version,
		"created_at": f.CreatedAt.Format(time.RFC3339),
	}
	if f.EffectiveFrom != nil {
		v["effective_date"] = f.EffectiveFrom.Format("2006-01-02")
	}
	return v
}

func (h *PayrollSettingsHandler) ListFormulas(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	rows, err := h.svc.ListFormulas(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list formulas")
		return
	}
	want := r.URL.Query().Get("type")
	out := make([]map[string]any, 0, len(rows))
	for _, f := range rows {
		if want != "" && f.Type != want {
			continue
		}
		out = append(out, formulaView(f))
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

// ReliefStatus reports whether a relief is currently active for the tenant.
func (h *PayrollSettingsHandler) ReliefStatus(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	rtype := r.URL.Query().Get("relief_type")
	row, err := h.orm.PayrollRelief.Query().
		Where(payrollrelief.TenantID(scope.TenantID), payrollrelief.TypeEQ(rtype)).
		Order(ent.Desc(payrollrelief.FieldUpdatedAt)).First(r.Context())
	if ent.IsNotFound(err) {
		writeJSON(w, http.StatusOK, map[string]any{"relief_type": rtype, "is_active": false})
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch relief")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"relief_type": row.Type,
		"is_active":   row.IsActive,
		"amount":      row.FixedLimit.StringFixed(2),
	})
}

type formulaMgmtBody struct {
	Operation     string `json:"operation"`
	ReliefType    string `json:"relief_type"`
	IsActive      bool   `json:"is_active"`
	EffectiveDate string `json:"effective_date"`
}

// FormulaManagement handles the relief toggle (operation=update_relief).
func (h *PayrollSettingsHandler) FormulaManagement(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var b formulaMgmtBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	if b.Operation != "update_relief" {
		writeError(w, http.StatusBadRequest, "bad_request", "unsupported operation")
		return
	}
	existing, err := h.orm.PayrollRelief.Query().
		Where(payrollrelief.TenantID(scope.TenantID), payrollrelief.TypeEQ(b.ReliefType)).
		Order(ent.Desc(payrollrelief.FieldUpdatedAt)).First(r.Context())
	if ent.IsNotFound(err) {
		row, cerr := h.orm.PayrollRelief.Create().
			SetTenantID(scope.TenantID).
			SetType(b.ReliefType).
			SetTitle(b.ReliefType).
			SetIsActive(b.IsActive).Save(r.Context())
		if cerr != nil {
			writeError(w, http.StatusBadRequest, "update_failed", cerr.Error())
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"relief_type": row.Type, "is_active": row.IsActive})
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch relief")
		return
	}
	row, err := existing.Update().SetIsActive(b.IsActive).Save(r.Context())
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"relief_type": row.Type, "is_active": row.IsActive})
}

// ---- General HR settings (per-tenant singleton) ----

func generalHRView(g *ent.GeneralHRSettings) map[string]any {
	return map[string]any{
		"id":                        g.ID,
		"overtime_normal_days":      g.OvertimeNormalDays.String(),
		"overtime_non_working_days": g.OvertimeNonWorkingDays.String(),
		"overtime_holidays":         g.OvertimeHolidays.String(),
		"partial_months":            g.PartialMonths,
		"round_off_currency":        g.RoundOffCurrency,
		"round_off_amount":          g.RoundOffAmount.StringFixed(2),
		"allow_backwards_payroll":   g.AllowBackwardsPayroll,
		"paye_enabled":              g.PayeEnabled,
		"nssf_enabled":              g.NssfEnabled,
		"shif_enabled":              g.ShifEnabled,
		"housing_levy_enabled":      g.HousingLevyEnabled,
		"nita_enabled":              g.NitaEnabled,
		"updated_at":                g.UpdatedAt.Format(time.RFC3339),
	}
}

func (h *PayrollSettingsHandler) GetGeneralHR(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	g, err := h.orm.GeneralHRSettings.Query().
		Where(generalhrsettings.TenantID(scope.TenantID)).Only(r.Context())
	if ent.IsNotFound(err) {
		// No row yet — return the effective defaults (statutory toggles ON) so the UI renders
		// the true behaviour instead of an empty envelope (which read as "everything off").
		// No id: the first save creates the row.
		writeJSON(w, http.StatusOK, map[string]any{
			"paye_enabled":         true,
			"nssf_enabled":         true,
			"shif_enabled":         true,
			"housing_levy_enabled": true,
			"nita_enabled":         true,
		})
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch settings")
		return
	}
	writeJSON(w, http.StatusOK, generalHRView(g))
}

type generalHRBody struct {
	PartialMonths         string `json:"partial_months"`
	RoundOffCurrency      string `json:"round_off_currency"`
	RoundOffAmount        string `json:"round_off_amount"`
	AllowBackwardsPayroll *bool  `json:"allow_backwards_payroll"`
	OvertimeNormalDays    string `json:"overtime_normal_days"`
	OvertimeNonWorking    string `json:"overtime_non_working_days"`
	OvertimeHolidays      string `json:"overtime_holidays"`
	PayeEnabled           *bool  `json:"paye_enabled"`
	NssfEnabled           *bool  `json:"nssf_enabled"`
	ShifEnabled           *bool  `json:"shif_enabled"`
	HousingLevyEnabled    *bool  `json:"housing_levy_enabled"`
	NitaEnabled           *bool  `json:"nita_enabled"`
}

func (h *PayrollSettingsHandler) UpsertGeneralHR(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var b generalHRBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	existing, err := h.orm.GeneralHRSettings.Query().
		Where(generalhrsettings.TenantID(scope.TenantID)).Only(r.Context())
	if ent.IsNotFound(err) {
		c := h.orm.GeneralHRSettings.Create().SetTenantID(scope.TenantID)
		if b.PartialMonths != "" {
			c = c.SetPartialMonths(b.PartialMonths)
		}
		if b.RoundOffCurrency != "" {
			c = c.SetRoundOffCurrency(b.RoundOffCurrency)
		}
		if d, e := parseDecimalDefault(b.RoundOffAmount); e == nil {
			c = c.SetRoundOffAmount(d)
		}
		if d, e := parseDecimalDefault(b.OvertimeNormalDays); e == nil {
			c = c.SetOvertimeNormalDays(d)
		}
		if d, e := parseDecimalDefault(b.OvertimeNonWorking); e == nil {
			c = c.SetOvertimeNonWorkingDays(d)
		}
		if d, e := parseDecimalDefault(b.OvertimeHolidays); e == nil {
			c = c.SetOvertimeHolidays(d)
		}
		if b.AllowBackwardsPayroll != nil {
			c = c.SetAllowBackwardsPayroll(*b.AllowBackwardsPayroll)
		}
		if b.PayeEnabled != nil {
			c = c.SetPayeEnabled(*b.PayeEnabled)
		}
		if b.NssfEnabled != nil {
			c = c.SetNssfEnabled(*b.NssfEnabled)
		}
		if b.ShifEnabled != nil {
			c = c.SetShifEnabled(*b.ShifEnabled)
		}
		if b.HousingLevyEnabled != nil {
			c = c.SetHousingLevyEnabled(*b.HousingLevyEnabled)
		}
		if b.NitaEnabled != nil {
			c = c.SetNitaEnabled(*b.NitaEnabled)
		}
		row, cerr := c.Save(r.Context())
		if cerr != nil {
			writeError(w, http.StatusBadRequest, "create_failed", cerr.Error())
			return
		}
		writeJSON(w, http.StatusOK, generalHRView(row))
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch settings")
		return
	}
	u := existing.Update()
	if b.PartialMonths != "" {
		u = u.SetPartialMonths(b.PartialMonths)
	}
	if b.RoundOffCurrency != "" {
		u = u.SetRoundOffCurrency(b.RoundOffCurrency)
	}
	if b.RoundOffAmount != "" {
		if d, e := decimal.NewFromString(b.RoundOffAmount); e == nil {
			u = u.SetRoundOffAmount(d)
		}
	}
	if b.OvertimeNormalDays != "" {
		if d, e := decimal.NewFromString(b.OvertimeNormalDays); e == nil {
			u = u.SetOvertimeNormalDays(d)
		}
	}
	if b.OvertimeNonWorking != "" {
		if d, e := decimal.NewFromString(b.OvertimeNonWorking); e == nil {
			u = u.SetOvertimeNonWorkingDays(d)
		}
	}
	if b.OvertimeHolidays != "" {
		if d, e := decimal.NewFromString(b.OvertimeHolidays); e == nil {
			u = u.SetOvertimeHolidays(d)
		}
	}
	if b.AllowBackwardsPayroll != nil {
		u = u.SetAllowBackwardsPayroll(*b.AllowBackwardsPayroll)
	}
	if b.PayeEnabled != nil {
		u = u.SetPayeEnabled(*b.PayeEnabled)
	}
	if b.NssfEnabled != nil {
		u = u.SetNssfEnabled(*b.NssfEnabled)
	}
	if b.ShifEnabled != nil {
		u = u.SetShifEnabled(*b.ShifEnabled)
	}
	if b.HousingLevyEnabled != nil {
		u = u.SetHousingLevyEnabled(*b.HousingLevyEnabled)
	}
	if b.NitaEnabled != nil {
		u = u.SetNitaEnabled(*b.NitaEnabled)
	}
	row, err := u.Save(r.Context())
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, generalHRView(row))
}
