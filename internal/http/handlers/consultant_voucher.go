package handlers

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/pagination"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/docs"
	docseq "github.com/Bengo-Hub/erp-api/internal/modules/docs/sequence"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

type consultantVoucherBody struct {
	EmployeeID   string `json:"employee_id"`
	Title        string `json:"title"`
	Period       string `json:"period"`
	GrossAmount  string `json:"gross_amount"`
	Deductions   string `json:"deductions_amount"`
	IsResident   *bool  `json:"is_resident"`
	ProjectID    string `json:"project_id"`
	CostCenterID string `json:"cost_center_id"`
}

func (h *DocumentsHandler) consultantVoucherView(ctx context.Context, tenantID uuid.UUID, v *ent.ConsultantVoucher) map[string]any {
	out := map[string]any{
		"id": v.ID, "doc_number": v.DocNumber, "title": v.Title,
		"gross_amount": v.GrossAmount.StringFixed(2), "deductions_amount": v.DeductionsAmount.StringFixed(2),
		"wht_rate": v.WhtRate.String(), "wht_amount": v.WhtAmount.StringFixed(2),
		"net_amount": v.NetAmount.StringFixed(2), "currency": v.Currency, "is_resident": v.IsResident,
		"status": string(v.Status), "email_status": v.EmailStatus, "employee_id": v.EmployeeID,
		"created_at": v.CreatedAt.Format(time.RFC3339),
	}
	if v.Period != nil {
		out["period"] = v.Period.Format("2006-01-02")
	}
	if emp, err := h.payroll.GetEmployee(ctx, tenantID, v.EmployeeID); err == nil && emp != nil {
		out["name"] = strings.TrimSpace(emp.FirstName + " " + emp.LastName)
		out["employee_name"] = out["name"]
	}
	return out
}

func (h *DocumentsHandler) ListConsultantVouchers(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	p := pagination.Parse(r)
	status := r.URL.Query().Get("status")
	rows, total, pageTotal, err := h.payroll.ListConsultantVouchers(r.Context(), scope.TenantID, status, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list consultant vouchers")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, v := range rows {
		out = append(out, h.consultantVoucherView(r.Context(), scope.TenantID, v))
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"results": out, "count": total, "page_total": pageTotal.StringFixed(2),
		"limit": p.Limit, "offset": p.Offset,
	})
}

func (h *DocumentsHandler) CreateConsultantVoucher(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var b consultantVoucherBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "a valid consultant is required")
		return
	}
	gross, _ := decimal.NewFromString(b.GrossAmount)
	ded, _ := decimal.NewFromString(b.Deductions)
	docNo, _ := h.seq.GenerateNumber(r.Context(), scope.TenantID, docseq.DocTypePaymentVoucher)
	in := payroll.ConsultantVoucherInput{
		EmployeeID: empID, Title: b.Title, DocNumber: docNo,
		GrossAmount: gross, DeductionsAmount: ded,
		IsResident: b.IsResident == nil || *b.IsResident,
		CreatedBy:  &scope.UserID,
	}
	if t, perr := parseDate(b.Period); perr == nil {
		in.Period = &t
	} else if t, pok := parsePeriod(b.Period); pok {
		in.Period = &t
	}
	if id, e := uuid.Parse(b.ProjectID); e == nil {
		in.ProjectID = &id
	}
	if id, e := uuid.Parse(b.CostCenterID); e == nil {
		in.CostCenterID = &id
	}
	v, err := h.payroll.CreateConsultantVoucher(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, h.consultantVoucherView(r.Context(), scope.TenantID, v))
}

func (h *DocumentsHandler) GetConsultantVoucher(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	v, err := h.payroll.GetConsultantVoucher(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "voucher not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch voucher")
		return
	}
	writeJSON(w, http.StatusOK, h.consultantVoucherView(r.Context(), scope.TenantID, v))
}

// whtRatesView renders the tenant's WHT rates as percentage strings.
func whtRatesView(r payroll.WHTRates) map[string]string {
	return map[string]string{"resident_rate": r.Resident.String(), "non_resident_rate": r.NonResident.String()}
}

// GetWHTRates returns the tenant's resident and non-resident WHT rates on consultancy fees.
func (h *DocumentsHandler) GetWHTRates(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	rates, err := h.payroll.GetWHTRates(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load WHT rates")
		return
	}
	writeJSON(w, http.StatusOK, whtRatesView(rates))
}

// SaveWHTRates stores the tenant's WHT rates (percent). Both rates are required.
func (h *DocumentsHandler) SaveWHTRates(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var body struct {
		Resident    string `json:"resident_rate"`
		NonResident string `json:"non_resident_rate"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	res, err1 := decimal.NewFromString(body.Resident)
	non, err2 := decimal.NewFromString(body.NonResident)
	if err1 != nil || err2 != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "resident_rate and non_resident_rate are required numbers")
		return
	}
	rates, err := h.payroll.SaveWHTRates(r.Context(), scope.TenantID, payroll.WHTRates{Resident: res, NonResident: non})
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_rates", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, whtRatesView(rates))
}

func (h *DocumentsHandler) DeleteConsultantVoucher(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.payroll.DeleteConsultantVoucher(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusBadRequest, "delete_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
}

// ApproveConsultantVoucher approves the voucher (treasury posts the GL via the emitted event),
// then pays the net to the consultant via the treasury payout S2S (best-effort) and marks it paid.
func (h *DocumentsHandler) ApproveConsultantVoucher(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	v, err := h.payroll.ApproveConsultantVoucher(r.Context(), scope.TenantID, id, scope.UserID)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "voucher not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to approve")
		return
	}
	// Pay the net via treasury (best-effort; GL already posts from the event).
	if h.treasury != nil && v.NetAmount.GreaterThan(decimal.Zero) {
		payout := treasury.Payout{
			RecipientID:   v.EmployeeID.String(),
			Amount:        v.NetAmount.StringFixed(2),
			Currency:      v.Currency,
			PaymentMethod: "bank_transfer",
			ReferenceID:   "consultant-" + v.ID.String(),
			Description:   "Consultant payment " + v.DocNumber,
		}
		if derr := h.treasury.Disburse(r.Context(), scope.TenantID, []treasury.Payout{payout}, "consultant-"+v.ID.String()); derr == nil {
			_ = h.payroll.MarkConsultantVoucherPaid(r.Context(), scope.TenantID, id)
			if vv, gerr := h.payroll.GetConsultantVoucher(r.Context(), scope.TenantID, id); gerr == nil {
				v = vv
			}
		} else {
			h.log.Warn("consultant voucher disburse", zap.Error(derr))
		}
	}
	writeJSON(w, http.StatusOK, h.consultantVoucherView(r.Context(), scope.TenantID, v))
}

// voucherDocument maps a consultant voucher to the shared Document model for the branded PDF.
func (h *DocumentsHandler) voucherDocument(ctx context.Context, tenantID uuid.UUID, v *ent.ConsultantVoucher) *docs.Document {
	ti := h.tenantInfo(ctx, tenantID)
	name := ""
	if emp, err := h.payroll.GetEmployee(ctx, tenantID, v.EmployeeID); err == nil && emp != nil {
		name = strings.TrimSpace(emp.FirstName + " " + emp.LastName)
	}
	docDate := v.CreatedAt
	if v.Period != nil {
		docDate = *v.Period
	}
	whtPct := v.WhtRate.Mul(decimal.NewFromInt(100))
	lines := []docs.DocumentLine{
		{SortOrder: 1, Description: "Consultancy Fees (gross)", Quantity: decimal.NewFromInt(1), UnitPrice: v.GrossAmount, LineTotal: v.GrossAmount},
		{SortOrder: 2, Description: fmt.Sprintf("Less: Withholding Tax (%s%%)", whtPct.StringFixed(0)), Quantity: decimal.NewFromInt(1), UnitPrice: v.WhtAmount.Neg(), LineTotal: v.WhtAmount.Neg()},
	}
	if v.DeductionsAmount.GreaterThan(decimal.Zero) {
		lines = append(lines, docs.DocumentLine{SortOrder: 3, Description: "Less: Deductions", Quantity: decimal.NewFromInt(1), UnitPrice: v.DeductionsAmount.Neg(), LineTotal: v.DeductionsAmount.Neg()})
	}
	title := v.Title
	if title == "" {
		title = "Consultant Payment Voucher"
	}
	return &docs.Document{
		Type:               docs.DocTypePaymentVoucher,
		DocNumber:          v.DocNumber,
		TenantName:         ti.Name,
		TenantLogoURL:      ti.LogoURL,
		TenantAddress:      ti.Address,
		TenantPrimaryColor: ti.PrimaryColor,
		CustomerName:       name,
		DocDate:            docDate,
		Subtotal:           v.GrossAmount,
		TaxAmount:          v.WhtAmount,
		TotalAmount:        v.NetAmount,
		Currency:           v.Currency,
		Lines:              lines,
		Notes:              title,
		Status:             strings.ToUpper(string(v.Status)),
	}
}

func (h *DocumentsHandler) ConsultantVoucherPDF(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	v, err := h.payroll.GetConsultantVoucher(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "voucher not found")
		return
	}
	body, mime, err := h.docs.Generate(h.voucherDocument(r.Context(), scope.TenantID, v), docs.FormatPDF)
	if err != nil {
		h.log.Error("voucher pdf", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate voucher")
		return
	}
	streamDownload(w, body, mime, v.DocNumber+".pdf")
}

type emailVouchersBody struct {
	IDs     []string `json:"ids"`
	Message string   `json:"message"`
}

// EmailConsultantVouchers emails the selected vouchers (PDF attached) to each consultant.
func (h *DocumentsHandler) EmailConsultantVouchers(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	if h.notify == nil {
		writeError(w, http.StatusServiceUnavailable, "unavailable", "email delivery is not configured")
		return
	}
	var b emailVouchersBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	sent, skipped := 0, 0
	for _, idStr := range b.IDs {
		id, err := uuid.Parse(idStr)
		if err != nil {
			skipped++
			continue
		}
		v, err := h.payroll.GetConsultantVoucher(r.Context(), scope.TenantID, id)
		if err != nil {
			skipped++
			continue
		}
		emp, eerr := h.payroll.GetEmployee(r.Context(), scope.TenantID, v.EmployeeID)
		if eerr != nil || emp == nil || strings.TrimSpace(emp.Email) == "" {
			skipped++
			continue
		}
		pdf, mime, gerr := h.docs.Generate(h.voucherDocument(r.Context(), scope.TenantID, v), docs.FormatPDF)
		if gerr != nil {
			skipped++
			continue
		}
		msg := strings.TrimSpace(b.Message)
		if msg == "" {
			msg = "Please find attached your payment voucher."
		}
		body := fmt.Sprintf("<p>Dear %s,</p><p>%s</p><p>Regards,<br/>Accounts Payable</p>", strings.TrimSpace(emp.FirstName+" "+emp.LastName), msg)
		req := events.EmailRequest{
			To:      []string{emp.Email},
			Subject: "Payment Voucher " + v.DocNumber,
			Body:    body,
			HTML:    true,
			Attachments: []events.EmailAttachment{{
				Filename: v.DocNumber + ".pdf", ContentType: mime, ContentB64: base64.StdEncoding.EncodeToString(pdf),
			}},
		}
		if err := h.notify.RequestEmail(r.Context(), scope.TenantID, v.ID.String(), req); err != nil {
			skipped++
			continue
		}
		_ = h.payroll.SetConsultantVoucherEmailStatus(r.Context(), scope.TenantID, id, "Sent")
		sent++
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "queued", "queued": sent, "skipped": skipped})
}
