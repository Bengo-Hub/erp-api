package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebenefit"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeloan"
	"github.com/Bengo-Hub/erp-api/internal/ent/generalhrsettings"
	"github.com/Bengo-Hub/erp-api/internal/ent/loantype"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollcomponent"
	"github.com/Bengo-Hub/erp-api/internal/ent/recoveryline"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

// PayrollSettingsHandler serves /api/v1/hrm/payroll-settings/* (components, loans,
// formulas, relief, general HR settings). Reuses the payrollsettings service for
// formula resolution and direct tenant-scoped Ent access for the config tables.
type PayrollSettingsHandler struct {
	log *zap.Logger
	svc *payrollsettings.Service
	orm *ent.Client
	// rates reads treasury's approved statutory rates (nil when treasury is not configured).
	rates func(ctx context.Context) ([]treasury.StatutoryRate, error)
}

func NewPayrollSettingsHandler(log *zap.Logger, svc *payrollsettings.Service, orm *ent.Client) *PayrollSettingsHandler {
	return &PayrollSettingsHandler{log: log.Named("hrm.payroll-settings"), svc: svc, orm: orm}
}

// WithTreasuryRates wires the treasury statutory rate reader used by the platform rate sync.
func (h *PayrollSettingsHandler) WithTreasuryRates(f func(ctx context.Context) ([]treasury.StatutoryRate, error)) *PayrollSettingsHandler {
	h.rates = f
	return h
}

func (h *PayrollSettingsHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/payroll-settings", func(pr chi.Router) {
		pr.Get("/payroll-components", h.ListComponents)
		pr.Post("/payroll-components", h.CreateComponent)
		pr.Get("/payroll-components/{id}", h.GetComponent)
		pr.Put("/payroll-components/{id}", h.UpdateComponent)
		pr.Delete("/payroll-components/{id}", h.DeleteComponent)
		pr.Post("/payroll-components/{id}/activation", h.SetComponentActive)
		pr.Post("/payroll-components/{id}/revert", h.RevertComponent)

		// Earnings and deductions given to one employee (employee_pay_components.go).
		pr.Get("/employees/{employeeId}/components", h.ListEmployeeComponents)
		pr.Post("/employees/{employeeId}/components", h.SaveEmployeeComponent)
		pr.Put("/employees/{employeeId}/components/{id}", h.SaveEmployeeComponent)
		pr.Delete("/employees/{employeeId}/components/{id}", h.DeleteEmployeeComponent)

		pr.Get("/loans", h.ListLoans)
		pr.Post("/loans", h.CreateLoan)
		pr.Get("/loans/{id}", h.GetLoan)
		pr.Put("/loans/{id}", h.UpdateLoan)
		pr.Delete("/loans/{id}", h.DeleteLoan)
		pr.Get("/loans/{id}/recoveries", h.LoanRecoveries)

		// Loan types (the products an employee loan is issued under).
		pr.Get("/loan-types", h.ListLoanTypes)
		pr.Post("/loan-types", h.CreateLoanType)
		pr.Put("/loan-types/{id}", h.UpdateLoanType)
		pr.Delete("/loan-types/{id}", h.DeleteLoanType)

		pr.Get("/formulas", h.ListFormulas)
		pr.Get("/formulas/relief-status", h.ReliefStatus)
		pr.Get("/formulas/reliefs", h.ListReliefs)
		pr.Post("/formula-management", h.FormulaManagement)
		pr.Post("/formulas", h.CreateFormula)
		pr.Get("/formulas/{id}", h.GetFormula)
		pr.Put("/formulas/{id}", h.UpdateFormula)
		pr.Delete("/formulas/{id}", h.DeleteFormula)
		pr.Post("/formulas/{id}/customise", h.CustomiseFormula)
		pr.Post("/formulas/{id}/revert", h.RevertFormula)
		pr.Post("/platform/treasury-rate-sync", h.SyncTreasuryRates)

		pr.Get("/general-hr-settings", h.GetGeneralHR)
		pr.Post("/general-hr-settings", h.UpsertGeneralHR)
		pr.Put("/general-hr-settings/{id}", h.UpsertGeneralHR)
	})
}

// ---- Components ----

// componentView serialises a resolved component: its effective values plus where they come from
// (source platform or tenant), whether the tenant customised it and what drives it.
func componentView(rc payrollsettings.ResolvedComponent) map[string]any {
	c := rc.Component
	platformRow := rc.Source == payrollsettings.SourcePlatform || rc.Customised
	v := map[string]any{
		"id":             c.ID,
		"code":           rc.Code,
		"name":           rc.Title,
		"title":          rc.Title,
		"category":       c.Category,
		"mode":           c.Mode,
		"is_active":      rc.Active,
		"default_active": rc.DefaultActive,
		"source":         rc.Source,
		"is_platform":    platformRow,
		"customised":     rc.Customised,
		"managed_by":     rc.ManagedBy,
		"opt_in":         platformRow && !rc.Statutory && rc.ManagedBy == "",
		// assignable: switched on and given to employees one by one (not statutory, not driven by
		// its own module); reference_label names the number an assignment must carry, if any.
		"assignable":      payrollsettings.Assignable(rc),
		"reference_label": payrollsettings.ReferenceLabel(rc.Code),
		"non_cash":        c.NonCash,
		"statutory":       rc.Statutory,
		"checkoff":        c.Checkoff,
		// Default monetary config (employee + employer side) so the UI shows the rate/amount.
		"amount":              rc.Amount.StringFixed(2),
		"percentage":          rc.Percentage.StringFixed(2),
		"percent_of":          c.PercentOf,
		"employer_amount":     rc.EmployerAmount.StringFixed(2),
		"employer_percentage": rc.EmployerPercentage.StringFixed(2),
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
	tenant := h.settingsTenant(r, scope)
	rows, err := h.svc.ResolveComponents(r.Context(), tenant, r.URL.Query().Get("category"))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list components")
		return
	}
	activeOnly := r.URL.Query().Get("active") == "true"
	out := make([]map[string]any, 0, len(rows))
	for _, c := range rows {
		if activeOnly && !c.Active {
			continue
		}
		out = append(out, componentView(c))
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

// settingsTenant is the tenant whose payroll settings a request reads or writes: the platform
// tenant when a platform owner asks for scope=platform, else the caller's tenant.
func (h *PayrollSettingsHandler) settingsTenant(r *http.Request, scope RequestScope) uuid.UUID {
	if r.URL.Query().Get("scope") == "platform" && scope.Claims != nil && scope.Claims.IsPlatformOwner && h.svc.SystemTenant() != uuid.Nil {
		return h.svc.SystemTenant()
	}
	return scope.TenantID
}

// writeSettingsError maps payroll settings errors onto HTTP answers.
func writeSettingsError(w http.ResponseWriter, err error, fallback string) {
	switch {
	case errors.Is(err, payrollsettings.ErrNotFound), ent.IsNotFound(err):
		writeError(w, http.StatusNotFound, "not_found", "not found")
	case errors.Is(err, payrollsettings.ErrPlatformReadOnly):
		writeError(w, http.StatusForbidden, "platform_default", err.Error())
	case errors.Is(err, payrollsettings.ErrAlreadyCustomised):
		writeError(w, http.StatusConflict, "already_customised", err.Error())
	default:
		writeError(w, http.StatusBadRequest, fallback, err.Error())
	}
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
	c, err := h.svc.Component(r.Context(), h.settingsTenant(r, scope), id)
	if err != nil {
		writeSettingsError(w, err, "internal_error")
		return
	}
	writeJSON(w, http.StatusOK, componentView(*c))
}

// componentActionBody is the body of the activation endpoint.
type componentActionBody struct {
	IsActive *bool `json:"is_active"`
}

// SetComponentActive switches a component on or off for the tenant (opt-in catalogue items,
// statutory toggles, or the tenant's own components).
func (h *PayrollSettingsHandler) SetComponentActive(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b componentActionBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil || b.IsActive == nil {
		writeError(w, http.StatusBadRequest, "bad_request", "is_active is required")
		return
	}
	c, err := h.svc.SetComponentActive(r.Context(), h.settingsTenant(r, scope), id, *b.IsActive)
	if err != nil {
		writeSettingsError(w, err, "update_failed")
		return
	}
	writeJSON(w, http.StatusOK, componentView(*c))
}

// RevertComponent drops the tenant's choice for a platform component.
func (h *PayrollSettingsHandler) RevertComponent(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	c, err := h.svc.RevertComponent(r.Context(), scope.TenantID, id)
	if err != nil {
		writeSettingsError(w, err, "revert_failed")
		return
	}
	writeJSON(w, http.StatusOK, componentView(*c))
}

// decPtr parses an optional decimal field ("" = not sent).
func decPtr(s string) (*decimal.Decimal, error) {
	if s == "" {
		return nil, nil
	}
	d, err := decimal.NewFromString(s)
	if err != nil {
		return nil, err
	}
	return &d, nil
}

// customiseComponent stores a tenant's own values for a platform component.
func (h *PayrollSettingsHandler) customiseComponent(w http.ResponseWriter, r *http.Request, tenant, id uuid.UUID, b componentBody) {
	var ch payrollsettings.ComponentChoice
	ch.Active = b.IsActive
	ch.Title = b.title()
	var err error
	for _, f := range []struct {
		s   string
		dst **decimal.Decimal
	}{{b.Amount, &ch.Amount}, {b.Percentage, &ch.Percentage}, {b.EmployerAmount, &ch.EmployerAmount}, {b.EmployerPercentage, &ch.EmployerPercentage}} {
		if *f.dst, err = decPtr(f.s); err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "invalid amount or percentage")
			return
		}
	}
	c, err := h.svc.CustomiseComponent(r.Context(), tenant, id, ch)
	if err != nil {
		writeSettingsError(w, err, "update_failed")
		return
	}
	writeJSON(w, http.StatusOK, componentView(*c))
}

type componentBody struct {
	// Code is the stable catalogue code (platform components; optional for tenant ones).
	Code               string `json:"code"`
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
	tenant := h.settingsTenant(r, scope)
	c := h.orm.PayrollComponent.Create().
		SetTenantID(tenant).
		SetTitle(b.title()).
		SetIsActive(b.IsActive == nil || *b.IsActive)
	if b.Code != "" {
		c = c.SetWbCode(b.Code)
	}
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
	h.writeComponent(w, r, tenant, row.ID, http.StatusCreated)
}

// writeComponent answers with the resolved view of one component.
func (h *PayrollSettingsHandler) writeComponent(w http.ResponseWriter, r *http.Request, tenant, id uuid.UUID, status int) {
	c, err := h.svc.Component(r.Context(), tenant, id)
	if err != nil {
		writeSettingsError(w, err, "internal_error")
		return
	}
	writeJSON(w, status, componentView(*c))
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
	tenant := h.settingsTenant(r, scope)
	resolved, err := h.svc.Component(r.Context(), tenant, id)
	if err != nil {
		writeSettingsError(w, err, "internal_error")
		return
	}
	var b componentBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	existing := resolved.Component
	if existing.TenantID != tenant && scope.Claims != nil && scope.Claims.IsPlatformOwner && h.svc.IsPlatformTenant(existing.TenantID) {
		// The platform owner edits the platform component itself: the change reaches every
		// tenant that has not set its own values (same rule as platform formulas). The form's
		// on/off reflects the owner's own organisation, so it never retires the platform row.
		tenant = existing.TenantID
		b.IsActive = nil
	}
	if existing.TenantID != tenant {
		// A platform component: the tenant's edit is stored as its own values over the
		// platform row (customise), never as a copied component.
		h.customiseComponent(w, r, tenant, id, b)
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
	h.writeComponent(w, r, tenant, row.ID, http.StatusOK)
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
	tenant := h.settingsTenant(r, scope)
	c, err := h.svc.Component(r.Context(), tenant, id)
	if err != nil {
		writeSettingsError(w, err, "internal_error")
		return
	}
	if c.Component.TenantID != tenant {
		writeError(w, http.StatusForbidden, "platform_default",
			"this is a platform default: switch it off or revert your changes instead of deleting it")
		return
	}
	if c.Statutory && h.svc.IsPlatformTenant(tenant) {
		writeError(w, http.StatusConflict, "statutory_component", "statutory platform components cannot be deleted")
		return
	}
	if used, uerr := h.orm.EmployeeBenefit.Query().Where(employeebenefit.ComponentID(id)).Exist(r.Context()); uerr != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to check component use")
		return
	} else if used {
		writeError(w, http.StatusConflict, "component_in_use", "employees have benefits on this component; switch it off instead of deleting it")
		return
	}
	n, err := h.orm.PayrollComponent.Delete().
		Where(payrollcomponent.ID(id), payrollcomponent.TenantID(tenant)).Exec(r.Context())
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
		"balance":             decimal.Max(l.PrincipalAmount.Sub(l.AmountRepaid), decimal.Zero).StringFixed(2),
		"installments_paid":   l.NoOfInstallmentsPaid,
	}
	if l.MonthlyInstallment.IsPositive() {
		v["installments"] = l.PrincipalAmount.Div(l.MonthlyInstallment).Ceil().IntPart()
	}
	if l.LoanTypeID != nil {
		v["loan_type_id"] = *l.LoanTypeID
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
	LoanTypeID         string `json:"loan_type_id"`
	// NoOfInstallments sets the monthly installment to principal / installments when no
	// monthly_installment is given.
	NoOfInstallments int `json:"no_of_installments"`
}

// installment is the monthly installment from the body: the explicit amount, else the principal
// spread over the number of installments.
func (b loanBody) installment(principal decimal.Decimal) (decimal.Decimal, error) {
	if b.MonthlyInstallment == "" && b.NoOfInstallments > 0 {
		return principal.Div(decimal.NewFromInt(int64(b.NoOfInstallments))).RoundUp(2), nil
	}
	return parseRequiredDecimal(b.MonthlyInstallment, "monthly_installment")
}

// loanTypeOf validates an optional loan type id against the tenant's loan types.
func (h *PayrollSettingsHandler) loanTypeOf(r *http.Request, tenantID uuid.UUID, raw string) (*uuid.UUID, error) {
	if raw == "" {
		return nil, nil
	}
	id, err := uuid.Parse(raw)
	if err != nil {
		return nil, errors.New("loan_type_id is invalid")
	}
	ok, err := h.orm.LoanType.Query().Where(loantype.ID(id), loantype.TenantID(tenantID)).Exist(r.Context())
	if err != nil || !ok {
		return nil, errors.New("loan type not found")
	}
	return &id, nil
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
	install, err := b.installment(principal)
	if err != nil || !install.IsPositive() {
		writeError(w, http.StatusBadRequest, "bad_request", "monthly_installment or no_of_installments is required")
		return
	}
	loanType, err := h.loanTypeOf(r, scope.TenantID, b.LoanTypeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	if ok, eerr := h.orm.Employee.Query().Where(employee.ID(empID), employee.TenantID(scope.TenantID)).Exist(r.Context()); eerr != nil || !ok {
		writeError(w, http.StatusBadRequest, "bad_request", "employee not found")
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
		SetNillableLoanTypeID(loanType).
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
	if b.LoanTypeID != "" {
		lt, lerr := h.loanTypeOf(r, scope.TenantID, b.LoanTypeID)
		if lerr != nil {
			writeError(w, http.StatusBadRequest, "bad_request", lerr.Error())
			return
		}
		u = u.SetNillableLoanTypeID(lt)
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
	// A loan with recoveries on a payslip keeps its history; deactivate it instead.
	if used, uerr := h.orm.RecoveryLine.Query().Where(recoveryline.TenantID(scope.TenantID),
		recoveryline.RecoverableTypeEQ(recoveryline.RecoverableTypeLoan), recoveryline.RecoverableID(id)).Exist(r.Context()); uerr != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to check loan recoveries")
		return
	} else if used {
		writeError(w, http.StatusConflict, "loan_in_use", "this loan has payroll recoveries; deactivate it instead of deleting it")
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

// formulaView serialises a resolved formula row with where it comes from: source platform rows
// are inherited (read-only for the tenant, "Customise" makes the tenant's own copy), source
// tenant rows are the tenant's own versions (overrides_id names the platform row they replace).
func formulaView(rf payrollsettings.ResolvedFormula) map[string]any {
	f := rf.Formula
	v := map[string]any{
		"id":         f.ID,
		"name":       f.Title,
		"title":      f.Title,
		"type":       f.Type,
		"category":   f.Category,
		"is_current": f.IsCurrent,
		"version":    f.Version,
		"source":     rf.Source,
		"created_at": f.CreatedAt.Format(time.RFC3339),
	}
	if rf.OverridesID != nil {
		v["overrides_id"] = *rf.OverridesID
	}
	if f.EffectiveFrom != nil {
		v["effective_date"] = f.EffectiveFrom.Format("2006-01-02")
		v["effective_from"] = f.EffectiveFrom.Format("2006-01-02")
	}
	if f.EffectiveTo != nil {
		v["effective_to"] = f.EffectiveTo.Format("2006-01-02")
	}
	if f.RegulatorySource != nil {
		v["regulatory_source"] = *f.RegulatorySource
	}
	return v
}

// ListFormulas lists the tenant's own formulas plus every platform formula it has not customised,
// so a tenant with no rows of its own still sees the full inherited statutory set.
func (h *PayrollSettingsHandler) ListFormulas(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	rows, err := h.svc.ListFormulas(r.Context(), h.settingsTenant(r, scope))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list formulas")
		return
	}
	want := r.URL.Query().Get("type")
	out := make([]map[string]any, 0, len(rows))
	for _, f := range rows {
		if want != "" && f.Formula.Type != want {
			continue
		}
		out = append(out, formulaView(f))
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

// reliefView serialises one resolved relief.
func reliefView(rr payrollsettings.ResolvedRelief) map[string]any {
	v := map[string]any{
		"id":            rr.ID,
		"key":           rr.Key,
		"relief_type":   rr.Key,
		"type":          rr.Type,
		"title":         rr.Title,
		"is_active":     rr.IsActive,
		"statutory":     rr.Statutory,
		"source":        rr.Source,
		"actual_amount": rr.ActualAmount,
		"amount":        rr.FixedLimit.StringFixed(2),
		"fixed_limit":   rr.FixedLimit.StringFixed(2),
		"percentage":    rr.Percentage.StringFixed(2),
		"percent_of":    rr.PercentOf,
	}
	if rr.PlatformID != nil {
		v["platform_id"] = *rr.PlatformID
	}
	return v
}

// ListReliefs lists the tenant's resolved KRA reliefs (platform reliefs with its choices applied).
func (h *PayrollSettingsHandler) ListReliefs(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	rows, err := h.svc.ResolveReliefs(r.Context(), h.settingsTenant(r, scope))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list reliefs")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, rr := range rows {
		out = append(out, reliefView(rr))
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": out, "count": len(out)})
}

// ReliefStatus reports whether a relief is active for the tenant. relief_type accepts the UI codes
// (personal_relief, insurance_relief, housing_relief, ...) or a relief title.
func (h *PayrollSettingsHandler) ReliefStatus(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	rtype := r.URL.Query().Get("relief_type")
	rr, err := h.svc.Relief(r.Context(), h.settingsTenant(r, scope), rtype)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch relief")
		return
	}
	if rr == nil {
		writeJSON(w, http.StatusOK, map[string]any{"relief_type": rtype, "is_active": false})
		return
	}
	writeJSON(w, http.StatusOK, reliefView(*rr))
}

type formulaMgmtBody struct {
	Operation     string `json:"operation"`
	ReliefType    string `json:"relief_type"`
	IsActive      bool   `json:"is_active"`
	EffectiveDate string `json:"effective_date"`
}

// FormulaManagement handles relief choices: operation=update_relief switches a relief on or off
// (a small activation record over the platform relief), operation=revert_relief drops the
// tenant's choice so the platform relief applies again.
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
	tenant := h.settingsTenant(r, scope)
	var (
		rr  *payrollsettings.ResolvedRelief
		err error
	)
	switch b.Operation {
	case "update_relief":
		rr, err = h.svc.SetReliefActive(r.Context(), tenant, b.ReliefType, b.IsActive)
	case "revert_relief":
		rr, err = h.svc.RevertRelief(r.Context(), tenant, b.ReliefType)
	default:
		writeError(w, http.StatusBadRequest, "bad_request", "unsupported operation")
		return
	}
	if err != nil {
		writeSettingsError(w, err, "update_failed")
		return
	}
	if rr == nil {
		writeJSON(w, http.StatusOK, map[string]any{"relief_type": b.ReliefType, "is_active": false})
		return
	}
	writeJSON(w, http.StatusOK, reliefView(*rr))
}

// SyncTreasuryRates pulls treasury's approved statutory rates and applies newer changes to the
// platform formulas. Platform owner only.
func (h *PayrollSettingsHandler) SyncTreasuryRates(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	if scope.Claims == nil || !scope.Claims.IsPlatformOwner {
		writeError(w, http.StatusForbidden, "forbidden", "only the platform owner can sync platform rates")
		return
	}
	if h.rates == nil {
		writeError(w, http.StatusServiceUnavailable, "treasury_unavailable", "treasury is not configured")
		return
	}
	rates, err := h.rates(r.Context())
	if err != nil {
		writeError(w, http.StatusBadGateway, "treasury_unavailable", err.Error())
		return
	}
	res, err := h.svc.SyncTreasuryRates(r.Context(), rates)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "sync_failed", err.Error())
		return
	}
	out := make([]map[string]any, 0, len(res))
	for _, x := range res {
		out = append(out, map[string]any{
			"type": x.Type, "category": x.Category, "action": x.Action,
			"effective_from": x.EffectiveFrom.Format("2006-01-02"),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": out})
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
