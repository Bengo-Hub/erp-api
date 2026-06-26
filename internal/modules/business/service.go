// Package business implements slim per-tenant ERP business configuration: company settings
// and per-tenant document numbering (payslip/report). It intentionally owns NO branding
// (auth-api SoT, read via the branding S2S cache), NO tax rates (the payroll-tax tables own
// those), and NO pickup/address/service-type (ordering-service).
package business

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/companysettings"
)

// Service holds company-settings CRUD + the document-sequence generator. Tenant-scoped.
type Service struct {
	orm *ent.Client
	Seq *SequenceService
}

func NewService(orm *ent.Client) *Service {
	return &Service{orm: orm, Seq: NewSequenceService(orm)}
}

// SettingsInput is the upsert payload for a tenant's company settings.
type SettingsInput struct {
	LegalName               string
	KRAPin                  string
	NSSFEmployerNo          string
	SHIFEmployerNo          string
	ContactEmail            string
	ContactPhone            string
	PostalAddress           string
	PhysicalAddress         string
	FinancialYearStartMonth int
	DefaultCurrency         string
	Timezone                string
	DateFormat              string
	TimeFormat              string
}

// GetSettings returns the tenant's company settings (or ent.NotFound when unset).
func (s *Service) GetSettings(ctx context.Context, tenantID uuid.UUID) (*ent.CompanySettings, error) {
	return s.orm.CompanySettings.Query().Where(companysettings.TenantID(tenantID)).Only(ctx)
}

// UpsertSettings creates or updates the tenant's single company-settings row.
func (s *Service) UpsertSettings(ctx context.Context, tenantID uuid.UUID, in SettingsInput) (*ent.CompanySettings, error) {
	if in.FinancialYearStartMonth < 0 || in.FinancialYearStartMonth > 12 {
		return nil, fmt.Errorf("business: financial_year_start_month must be 0-12")
	}
	existing, err := s.orm.CompanySettings.Query().Where(companysettings.TenantID(tenantID)).Only(ctx)
	if ent.IsNotFound(err) {
		b := s.orm.CompanySettings.Create().
			SetTenantID(tenantID).
			SetLegalName(in.LegalName).SetKraPin(in.KRAPin).
			SetNssfEmployerNo(in.NSSFEmployerNo).SetShifEmployerNo(in.SHIFEmployerNo).
			SetContactEmail(in.ContactEmail).SetContactPhone(in.ContactPhone).
			SetPostalAddress(in.PostalAddress).SetPhysicalAddress(in.PhysicalAddress)
		if in.FinancialYearStartMonth > 0 {
			b = b.SetFinancialYearStartMonth(in.FinancialYearStartMonth)
		}
		if in.DefaultCurrency != "" {
			b = b.SetDefaultCurrency(in.DefaultCurrency)
		}
		if in.Timezone != "" {
			b = b.SetTimezone(in.Timezone)
		}
		if in.DateFormat != "" {
			b = b.SetDateFormat(in.DateFormat)
		}
		if in.TimeFormat != "" {
			b = b.SetTimeFormat(in.TimeFormat)
		}
		row, cerr := b.Save(ctx)
		if cerr != nil {
			return nil, fmt.Errorf("business: create settings: %w", cerr)
		}
		// First-time tenant bootstrap: ensure default document sequences exist for this tenant.
		// Best-effort + idempotent — a sequence hiccup must not fail the settings save.
		if err := s.Seq.EnsureDefaults(ctx, tenantID); err != nil {
			return row, nil //nolint:nilerr // defaults are best-effort
		}
		return row, nil
	}
	if err != nil {
		return nil, fmt.Errorf("business: load settings: %w", err)
	}
	u := existing.Update().
		SetLegalName(in.LegalName).SetKraPin(in.KRAPin).
		SetNssfEmployerNo(in.NSSFEmployerNo).SetShifEmployerNo(in.SHIFEmployerNo).
		SetContactEmail(in.ContactEmail).SetContactPhone(in.ContactPhone).
		SetPostalAddress(in.PostalAddress).SetPhysicalAddress(in.PhysicalAddress)
	if in.FinancialYearStartMonth > 0 {
		u = u.SetFinancialYearStartMonth(in.FinancialYearStartMonth)
	}
	if in.DefaultCurrency != "" {
		u = u.SetDefaultCurrency(in.DefaultCurrency)
	}
	if in.Timezone != "" {
		u = u.SetTimezone(in.Timezone)
	}
	if in.DateFormat != "" {
		u = u.SetDateFormat(in.DateFormat)
	}
	if in.TimeFormat != "" {
		u = u.SetTimeFormat(in.TimeFormat)
	}
	row, uerr := u.Save(ctx)
	if uerr != nil {
		return nil, fmt.Errorf("business: update settings: %w", uerr)
	}
	return row, nil
}

// ---- Document sequences (config CRUD; generation lives in SequenceService) ----

// ListSequences returns the tenant's document-sequence configs.
func (s *Service) ListSequences(ctx context.Context, tenantID uuid.UUID) ([]*ent.DocumentSequence, error) {
	return s.Seq.List(ctx, tenantID)
}

// PrefixInput configures one document sequence's formatting.
type PrefixInput struct {
	DocType    string
	Prefix     string
	Separator  string
	DateFormat string
	Padding    int
	ResetFreq  string
}

// UpsertSequenceConfig sets the prefix/format for a (tenant, doc_type) sequence.
func (s *Service) UpsertSequenceConfig(ctx context.Context, tenantID uuid.UUID, in PrefixInput) (*ent.DocumentSequence, error) {
	return s.Seq.UpsertConfig(ctx, tenantID, in)
}

// NextNumber atomically generates the next formatted number for a doc type.
func (s *Service) NextNumber(ctx context.Context, tenantID uuid.UUID, docType string) (string, error) {
	return s.Seq.GenerateNumber(ctx, tenantID, docType)
}
