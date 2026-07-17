// Package staffpurchase owns the ERP side of POS staff-credit: it turns a POS staff purchase (goods
// taken on credit/layaway funded from salary) into a StaffPurchaseDeduction recoverable that payroll
// recovers over installments. Called S2S by pos-api, keyed on the shared auth user id.
package staffpurchase

import (
	"context"
	"errors"
	"strings"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/staffpurchasededuction"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
	subs "github.com/Bengo-Hub/erp-api/internal/platform/subscriptions"
)

// ErrNotEntitled is returned when the tenant's plan does not include staff_fund_from_salary.
var ErrNotEntitled = errors.New("staff_fund_from_salary feature not included in the tenant's plan")

// FeatureCode is the premium entitlement that unlocks staff fund-from-salary credit.
const FeatureCode = "staff_fund_from_salary"

// Service creates + reconciles staff-purchase recoverables.
type Service struct {
	orm       *ent.Client
	employees *employees.Service
	subs      *subs.Client
	publisher *events.Publisher
	log       *zap.Logger
}

func NewService(orm *ent.Client, empSvc *employees.Service, subsClient *subs.Client, publisher *events.Publisher, log *zap.Logger) *Service {
	return &Service{orm: orm, employees: empSvc, subs: subsClient, publisher: publisher, log: log.Named("staffpurchase")}
}

// CreateInput is the S2S payload from pos-api.
type CreateInput struct {
	AuthUserID        uuid.UUID
	Origin            string // layaway | credit_sale
	POSReference      string
	SourceKey         string // pos:layaway:<id> | pos:credit_sale:<id>
	Principal         decimal.Decimal
	InstallmentAmount decimal.Decimal
	InstallmentsTotal int
	EmployeeEmail     string
	EmployeeName      string
}

// Result is returned to pos-api.
type Result struct {
	ID          uuid.UUID       `json:"id"`
	EmployeeID  uuid.UUID       `json:"employee_id"`
	Outstanding decimal.Decimal `json:"outstanding"`
	Status      string          `json:"status"`
}

// Create is idempotent on (tenant, source_key): a replay returns the existing recoverable. It
// resolves/creates the employee from the auth user id (get-or-create, so an as-yet-unsynced staff
// member is materialised just-in-time), enforces the premium feature, then creates the recoverable.
func (s *Service) Create(ctx context.Context, tenantID uuid.UUID, in CreateInput) (*Result, error) {
	if strings.TrimSpace(in.SourceKey) == "" {
		return nil, errors.New("source_key is required")
	}
	// Idempotency: return the existing recoverable if this source_key was already ingested.
	if existing, err := s.orm.StaffPurchaseDeduction.Query().
		Where(staffpurchasededuction.TenantID(tenantID), staffpurchasededuction.SourceKey(in.SourceKey)).
		Only(ctx); err == nil && existing != nil {
		return s.toResult(existing), nil
	}

	// Premium gate (fail-open on pricing-API outage; hard-deny only on an authoritative "not entitled").
	if s.subs != nil && !s.subs.HasFeature(ctx, tenantID, FeatureCode) {
		return nil, ErrNotEntitled
	}

	// Resolve or create the employee from the shared auth user id.
	emp, err := s.employees.UpsertFromAuthUser(ctx, tenantID, in.AuthUserID, in.EmployeeEmail, in.EmployeeName, nil, false)
	if err != nil {
		return nil, err
	}

	origin := staffpurchasededuction.Origin(in.Origin)
	if origin != staffpurchasededuction.OriginLayaway && origin != staffpurchasededuction.OriginCreditSale {
		origin = staffpurchasededuction.OriginCreditSale
	}
	install := in.InstallmentAmount
	if !install.IsPositive() {
		install = in.Principal // default: recover in one period
	}

	row, err := s.orm.StaffPurchaseDeduction.Create().
		SetTenantID(tenantID).
		SetEmployeeID(emp.ID).
		SetOrigin(origin).
		SetPosReference(in.POSReference).
		SetSourceKey(in.SourceKey).
		SetPrincipal(in.Principal).
		SetInstallmentAmount(install).
		SetInstallmentsTotal(in.InstallmentsTotal).
		SetStatus("active").
		SetIsActive(true).
		Save(ctx)
	if err != nil {
		return nil, err
	}

	// Reverse-sync hint: let POS learn this employee's HR number (best-effort).
	if s.publisher != nil {
		empNo := ""
		if emp.EmployeeNumber != nil {
			empNo = *emp.EmployeeNumber
		}
		_ = s.publisher.Publish(ctx, tenantID, emp.ID, "employee.upserted", map[string]any{
			"employee_id":     emp.ID.String(),
			"auth_user_id":    in.AuthUserID.String(),
			"employee_number": empNo,
			"name":            in.EmployeeName,
		})
	}
	return s.toResult(row), nil
}

func (s *Service) toResult(r *ent.StaffPurchaseDeduction) *Result {
	return &Result{
		ID:          r.ID,
		EmployeeID:  r.EmployeeID,
		Outstanding: r.Principal.Sub(r.AmountRecovered),
		Status:      r.Status.String(),
	}
}

// StatusRow summarises one employee's outstanding staff-purchase balance for the reconcile view.
type StatusRow struct {
	EmployeeID     uuid.UUID       `json:"employee_id"`
	EmployeeNumber string          `json:"employee_number"`
	OpenCount      int             `json:"open_count"`
	Principal      decimal.Decimal `json:"principal"`
	Recovered      decimal.Decimal `json:"recovered"`
	Outstanding    decimal.Decimal `json:"outstanding"`
}

// SyncStatus returns per-employee staff-purchase summaries (open balances + recovery progress).
func (s *Service) SyncStatus(ctx context.Context, tenantID uuid.UUID) ([]StatusRow, error) {
	rows, err := s.orm.StaffPurchaseDeduction.Query().
		Where(staffpurchasededuction.TenantID(tenantID)).
		All(ctx)
	if err != nil {
		return nil, err
	}
	byEmp := map[uuid.UUID]*StatusRow{}
	for _, r := range rows {
		sr := byEmp[r.EmployeeID]
		if sr == nil {
			sr = &StatusRow{EmployeeID: r.EmployeeID}
			byEmp[r.EmployeeID] = sr
		}
		sr.Principal = sr.Principal.Add(r.Principal)
		sr.Recovered = sr.Recovered.Add(r.AmountRecovered)
		if r.IsActive {
			sr.OpenCount++
		}
	}
	out := make([]StatusRow, 0, len(byEmp))
	for _, sr := range byEmp {
		sr.Outstanding = sr.Principal.Sub(sr.Recovered)
		out = append(out, *sr)
	}
	return out, nil
}
