package handlers

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/authtenant"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebankaccount"
	"github.com/Bengo-Hub/erp-api/internal/modules/docs"
	"github.com/Bengo-Hub/erp-api/internal/modules/docs/adapters"
	docseq "github.com/Bengo-Hub/erp-api/internal/modules/docs/sequence"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
	"github.com/Bengo-Hub/erp-api/internal/modules/reports"
	platformauth "github.com/Bengo-Hub/erp-api/internal/platform/auth"
)

// DocumentsHandler serves authenticated document downloads (payslip PDFs). It owns the
// branding resolution + adapter wiring; report exports are mounted on ReportsHandler.
type DocumentsHandler struct {
	log      *zap.Logger
	orm      *ent.Client
	branding *platformauth.BrandingClient
	payroll  *payroll.Service
	docs     *docs.DocumentService
	seq      *docseq.Service
}

func NewDocumentsHandler(
	log *zap.Logger,
	orm *ent.Client,
	branding *platformauth.BrandingClient,
	payrollSvc *payroll.Service,
	docSvc *docs.DocumentService,
	seq *docseq.Service,
) *DocumentsHandler {
	return &DocumentsHandler{
		log:      log.Named("documents"),
		orm:      orm,
		branding: branding,
		payroll:  payrollSvc,
		docs:     docSvc,
		seq:      seq,
	}
}

func (h *DocumentsHandler) RegisterRoutes(r chi.Router) {
	r.Get("/hrm/payroll/{id}/pdf", h.PayslipPDF)
}

// PayslipPDF streams a tenant-branded payslip PDF. Gated on hrm.payroll.view PLUS a
// self-or-manager check: a user with manage/process payroll permission (or a platform
// owner / superuser / service) may download any payslip; everyone else may download
// only their own (matching their SSO user on the employee record).
func (h *DocumentsHandler) PayslipPDF(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}

	ps, err := h.payroll.GetPayslip(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "payslip not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch payslip")
		return
	}

	emp, err := h.payroll.GetEmployee(r.Context(), scope.TenantID, ps.EmployeeID)
	if err != nil && !ent.IsNotFound(err) {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch employee")
		return
	}

	if !h.canDownloadPayslip(scope, emp) {
		writeError(w, http.StatusForbidden, "forbidden", "not permitted to download this payslip")
		return
	}

	// Resolve tenant branding + employee identity, adapt, generate, stream.
	ti := h.tenantInfo(r.Context(), scope.TenantID)
	in := h.payslipInput(r.Context(), scope.TenantID, ps, emp)

	lines, _ := h.payroll.LoadPayslipLines(r.Context(), scope.TenantID, ps.ID)
	breakdown := payroll.BuildPayslipBreakdownWithLines(ps, lines)
	doc := adapters.PayslipToDocument(in, breakdown, ti)

	body, mime, err := h.docs.Generate(doc, docs.FormatPDF)
	if err != nil {
		h.log.Error("payslip pdf generate", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate payslip")
		return
	}
	streamDownload(w, body, mime, in.DocNumber+".pdf")
}

// canDownloadPayslip enforces the self-or-manager rule. Managers (manage/process perm)
// and platform/superuser/service principals may download any payslip; a regular user may
// download only the payslip of the employee linked to their SSO user.
func (h *DocumentsHandler) canDownloadPayslip(scope RequestScope, emp *ent.Employee) bool {
	c := scope.Claims
	if c != nil && (c.IsPlatformOwner || c.IsSuperuser() || c.IsService ||
		c.HasPermission(permPayrollManage) || c.HasPermission(permPayrollProcess)) {
		return true
	}
	if rbacService != nil && scope.UserID != uuid.Nil {
		ctx := scope.Ctx
		if ctx == nil {
			ctx = context.Background()
		}
		if perms, err := rbacService.GetUserPermissions(ctx, scope.TenantID, scope.UserID); err == nil {
			for _, p := range perms {
				if p.PermissionCode == permPayrollManage || p.PermissionCode == permPayrollProcess {
					return true
				}
			}
		}
	}
	// Self: the requesting SSO user owns the employee record.
	if emp != nil && emp.UserID != nil && scope.UserID != uuid.Nil && *emp.UserID == scope.UserID {
		return true
	}
	return false
}

// payslipInput assembles the employee/period identity for the payslip document,
// allocating a PAY-prefixed document number.
func (h *DocumentsHandler) payslipInput(ctx context.Context, tenantID uuid.UUID, ps *ent.Payslip, emp *ent.Employee) adapters.PayslipInput {
	name, number := h.payroll.EmployeeLabel(ctx, tenantID, ps.EmployeeID)
	in := adapters.PayslipInput{
		EmployeeName:   name,
		EmployeeNumber: number,
		Currency:       "KES",
		Status:         ps.ApprovalStatus,
	}
	if emp != nil {
		in.EmployeeEmail = emp.Email
		in.EmployeeKraPin = emp.PinNo
	}
	if ps.PaymentPeriod != nil {
		in.PeriodLabel = ps.PaymentPeriod.Format("January 2006")
	}
	if ps.Published && ps.UpdatedAt.Year() > 1 {
		in.PaymentDate = ps.UpdatedAt.Format("02 Jan 2006")
	}
	// Document number: prefer a stored batch ref, else allocate a PAY sequence number.
	if num, err := h.seq.GenerateNumber(ctx, tenantID, docseq.DocTypePayslip); err == nil {
		in.DocNumber = num
	} else {
		in.DocNumber = "PAY-" + ps.ID.String()[:8]
	}
	// Primary bank account (paid-to block).
	if ba, err := h.orm.EmployeeBankAccount.Query().
		Where(employeebankaccount.TenantID(tenantID), employeebankaccount.EmployeeID(ps.EmployeeID), employeebankaccount.IsPrimary(true)).
		First(ctx); err == nil && ba != nil {
		in.Bank = &docs.BankDetails{
			BankName:      ba.BankName,
			BranchCode:    ba.BranchName,
			AccountName:   ba.AccountName,
			AccountNumber: ba.AccountNumber,
		}
	}
	return in
}

// tenantInfo resolves the tenant slug from the local AuthTenant shadow, fetches auth-api
// branding (logo/colors/name/address/KRA pin) and maps it to a docs TenantInfo. Branding
// failures degrade gracefully — the document renders with the slug + default palette.
func (h *DocumentsHandler) tenantInfo(ctx context.Context, tenantID uuid.UUID) adapters.TenantInfo {
	slug := ""
	if at, err := h.orm.AuthTenant.Query().Where(authtenant.ID(tenantID)).Only(ctx); err == nil {
		slug = at.Slug
	}
	var bd *adapters.BrandingData
	if slug != "" && h.branding != nil {
		if b, err := h.branding.GetBySlug(ctx, slug); err == nil && b != nil {
			bd = &adapters.BrandingData{
				Name:         b.Name,
				Slug:         b.Slug,
				LogoURL:      b.LogoURL,
				PrimaryColor: b.PrimaryColor,
				KraPin:       b.KraPin,
				Address:      b.Address,
			}
		}
	}
	return adapters.FromBranding(slug, bd)
}

// ReportToDocumentSvc adapts + generates a report export. It is exported on
// DocumentsHandler so ReportsHandler can reuse the same branding/adapter/generate path.
func (h *DocumentsHandler) GenerateReport(ctx context.Context, tenantID uuid.UUID, rep *reports.Report, format docs.Format) ([]byte, string, string, error) {
	ti := h.tenantInfo(ctx, tenantID)
	docNumber := ""
	if num, err := h.seq.GenerateNumber(ctx, tenantID, docseq.DocTypePayrollReport); err == nil {
		docNumber = num
	}
	doc := adapters.ReportToDocument(rep, docNumber, ti)
	body, mime, err := h.docs.Generate(doc, format)
	if err != nil {
		return nil, "", "", err
	}
	filename := rep.Report
	if filename == "" {
		filename = "report"
	}
	ext := "pdf"
	if format == docs.FormatXLSX {
		ext = "xlsx"
	} else if format == docs.FormatCSV {
		ext = "csv"
	}
	return body, mime, fmt.Sprintf("%s-%s.%s", filename, time.Now().Format("20060102"), ext), nil
}

// streamDownload writes a binary document as an attachment download.
func streamDownload(w http.ResponseWriter, body []byte, mime, filename string) {
	w.Header().Set("Content-Type", mime)
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%q", filename))
	w.Header().Set("Content-Length", fmt.Sprintf("%d", len(body)))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}
