package business

import (
	"context"
	"fmt"
	"math/rand"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	entdocseq "github.com/Bengo-Hub/erp-api/internal/ent/documentsequence"
)

// Doc type constants — must match DocumentSequence.doc_type values.
const (
	DocTypePayslip       = "payslip"
	DocTypePayrollReport = "payroll_report"
	DocTypeP9            = "p9"
	DocTypeP10A          = "p10a"
)

type seqConfig struct {
	Prefix     string
	Separator  string
	DateFormat string
	Padding    int
	ResetFreq  string
}

var seqDefaults = map[string]seqConfig{
	DocTypePayslip:       {Prefix: "PAY", Separator: "-", DateFormat: "YYMMDD", Padding: 6, ResetFreq: "never"},
	DocTypePayrollReport: {Prefix: "RPT", Separator: "-", DateFormat: "YYMMDD", Padding: 6, ResetFreq: "never"},
	DocTypeP9:            {Prefix: "P9", Separator: "-", DateFormat: "YYYY", Padding: 6, ResetFreq: "yearly"},
	DocTypeP10A:          {Prefix: "P10A", Separator: "-", DateFormat: "YYYY", Padding: 6, ResetFreq: "yearly"},
}

// SequenceService generates per-tenant atomic document numbers via optimistic compare-and-set
// on DocumentSequence.current_val (race-safe without raw SQL locks). Mirrors inventory-api.
type SequenceService struct {
	ent *ent.Client
}

func NewSequenceService(client *ent.Client) *SequenceService { return &SequenceService{ent: client} }

// List returns the tenant's sequence configs.
func (s *SequenceService) List(ctx context.Context, tenantID uuid.UUID) ([]*ent.DocumentSequence, error) {
	return s.ent.DocumentSequence.Query().Where(entdocseq.TenantID(tenantID)).All(ctx)
}

// UpsertConfig sets the formatting for a (tenant, doc_type) sequence (preserving current_val).
func (s *SequenceService) UpsertConfig(ctx context.Context, tenantID uuid.UUID, in PrefixInput) (*ent.DocumentSequence, error) {
	if in.DocType == "" {
		return nil, fmt.Errorf("business: doc_type required")
	}
	row, err := s.getOrCreate(ctx, tenantID, in.DocType)
	if err != nil {
		return nil, err
	}
	u := row.Update()
	if in.Prefix != "" {
		u = u.SetPrefix(in.Prefix)
	}
	if in.Separator != "" {
		u = u.SetSeparator(in.Separator)
	}
	u = u.SetDateFormat(in.DateFormat)
	if in.Padding > 0 {
		u = u.SetPadding(in.Padding)
	}
	if in.ResetFreq != "" {
		u = u.SetResetFreq(in.ResetFreq)
	}
	return u.Save(ctx)
}

// GenerateNumber atomically increments the (tenant, docType) counter and returns a formatted
// number. Retries up to 5 times on CAS contention.
func (s *SequenceService) GenerateNumber(ctx context.Context, tenantID uuid.UUID, docType string) (string, error) {
	var lastErr error
	for attempt := 0; attempt < 5; attempt++ {
		if attempt > 0 {
			time.Sleep(time.Duration(10*(1<<attempt))*time.Millisecond + time.Duration(rand.Intn(20))*time.Millisecond)
		}
		row, err := s.getOrCreate(ctx, tenantID, docType)
		if err != nil {
			lastErr = err
			continue
		}
		old := row.CurrentVal
		affected, err := s.ent.DocumentSequence.Update().
			Where(entdocseq.IDEQ(row.ID), entdocseq.CurrentValEQ(old)).
			SetCurrentVal(old + 1).
			Save(ctx)
		if err != nil {
			lastErr = err
			continue
		}
		if affected == 0 {
			lastErr = fmt.Errorf("sequence CAS contention")
			continue
		}
		return formatNumber(row, old+1, time.Now()), nil
	}
	return "", fmt.Errorf("business: generate document number after retries: %w", lastErr)
}

func (s *SequenceService) getOrCreate(ctx context.Context, tenantID uuid.UUID, docType string) (*ent.DocumentSequence, error) {
	row, err := s.ent.DocumentSequence.Query().
		Where(entdocseq.TenantID(tenantID), entdocseq.DocType(docType)).Only(ctx)
	if err == nil {
		return row, nil
	}
	if !ent.IsNotFound(err) {
		return nil, err
	}
	cfg, ok := seqDefaults[docType]
	if !ok {
		cfg = seqConfig{Prefix: strings.ToUpper(docType), Separator: "-", DateFormat: "YYMMDD", Padding: 6, ResetFreq: "never"}
	}
	created, err := s.ent.DocumentSequence.Create().
		SetTenantID(tenantID).SetDocType(docType).
		SetPrefix(cfg.Prefix).SetSeparator(cfg.Separator).SetDateFormat(cfg.DateFormat).
		SetPadding(cfg.Padding).SetResetFreq(cfg.ResetFreq).SetCurrentVal(0).
		Save(ctx)
	if err != nil {
		// Likely a concurrent create — re-read.
		if row2, e2 := s.ent.DocumentSequence.Query().Where(entdocseq.TenantID(tenantID), entdocseq.DocType(docType)).Only(ctx); e2 == nil {
			return row2, nil
		}
		return nil, err
	}
	return created, nil
}

func formatNumber(row *ent.DocumentSequence, val int64, now time.Time) string {
	parts := make([]string, 0, 3)
	if row.Prefix != "" {
		parts = append(parts, row.Prefix)
	}
	if d := formatDate(row.DateFormat, now); d != "" {
		parts = append(parts, d)
	}
	parts = append(parts, fmt.Sprintf("%0*d", row.Padding, val))
	sep := row.Separator
	if sep == "" {
		sep = "-"
	}
	return strings.Join(parts, sep)
}

func formatDate(format string, now time.Time) string {
	switch strings.ToUpper(format) {
	case "YYYYMMDD":
		return now.Format("20060102")
	case "YYMMDD":
		return now.Format("060102")
	case "MMYY":
		return now.Format("0106")
	case "YYYY":
		return now.Format("2006")
	default:
		return ""
	}
}
