package sequence

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"math/rand"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	entdocseq "github.com/Bengo-Hub/erp-api/internal/ent/documentsequence"
)

// DocType constants — must match ent document_sequence.doc_type values.
const (
	DocTypePayslip        = "payslip"
	DocTypePayrollReport  = "payroll_report"
	DocTypePaymentVoucher = "payment_voucher"
)

// Default sequence configs seeded per tenant on first use.
var defaults = map[string]Config{
	DocTypePayslip:        {Prefix: "PAY", Separator: "-", DateFormat: "YYMMDD", Padding: 6, ResetFreq: "never"},
	DocTypePayrollReport:  {Prefix: "RPT", Separator: "-", DateFormat: "YYMMDD", Padding: 6, ResetFreq: "never"},
	DocTypePaymentVoucher: {Prefix: "VOC", Separator: "-", DateFormat: "YYMMDD", Padding: 6, ResetFreq: "never"},
}

// Config holds the formatting settings for a document sequence.
type Config struct {
	Prefix     string     `json:"prefix"`
	Separator  string     `json:"separator"`
	DateFormat string     `json:"date_format"`
	Padding    int        `json:"padding"`
	ResetFreq  string     `json:"reset_freq"` // daily, monthly, yearly, never
	CurrentVal int64      `json:"current_val"`
	LastReset  *time.Time `json:"last_reset,omitempty"`
}

// Service provides atomic document number generation using SELECT FOR UPDATE.
type Service struct {
	db  *sql.DB
	ent *ent.Client
}

// New creates a new sequence Service.
func New(db *sql.DB, entClient *ent.Client) *Service {
	return &Service{db: db, ent: entClient}
}

// GenerateNumber atomically increments the sequence and returns a formatted document number.
// Uses SELECT FOR UPDATE with 3 retries + exponential backoff.
func (s *Service) GenerateNumber(ctx context.Context, tenantID uuid.UUID, docType string) (string, error) {
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if attempt > 0 {
			jitter := time.Duration(rand.Intn(50)) * time.Millisecond
			time.Sleep(time.Duration(50*(1<<attempt))*time.Millisecond + jitter)
		}
		num, err := s.atomicIncrement(ctx, tenantID, docType)
		if err == nil {
			return num, nil
		}
		lastErr = err
	}
	return "", fmt.Errorf("sequence generate after 3 attempts: %w", lastErr)
}

// PreviewNextNumber returns the next formatted number WITHOUT incrementing the counter.
func (s *Service) PreviewNextNumber(ctx context.Context, tenantID uuid.UUID, docType string) (string, error) {
	cfg, err := s.getOrCreateConfig(ctx, tenantID, docType)
	if err != nil {
		return "", err
	}
	nextVal := cfg.CurrentVal + 1
	return formatNumber(*cfg, nextVal, time.Now()), nil
}

// GetConfig returns the sequence configuration for a doc type.
func (s *Service) GetConfig(ctx context.Context, tenantID uuid.UUID, docType string) (*Config, error) {
	return s.getOrCreateConfig(ctx, tenantID, docType)
}

// ListConfigs returns all sequence configs for a tenant, creating defaults for missing types.
func (s *Service) ListConfigs(ctx context.Context, tenantID uuid.UUID) ([]*Config, error) {
	configs := make([]*Config, 0, len(defaults))
	for dt := range defaults {
		cfg, err := s.getOrCreateConfig(ctx, tenantID, dt)
		if err != nil {
			return nil, err
		}
		configs = append(configs, cfg)
	}
	return configs, nil
}

// UpdateConfig updates format settings (prefix, separator, date_format, padding, reset_freq).
// Does NOT change current_val — use ResetCounter for that.
func (s *Service) UpdateConfig(ctx context.Context, tenantID uuid.UUID, docType string, updates Config) error {
	if _, err := s.getOrCreateConfig(ctx, tenantID, docType); err != nil {
		return err
	}
	upd := s.ent.DocumentSequence.Update().
		Where(entdocseq.TenantID(tenantID), entdocseq.DocType(docType)).
		SetSeparator(updates.Separator).
		SetPadding(updates.Padding).
		SetResetFreq(updates.ResetFreq)
	if updates.Prefix != "" {
		upd = upd.SetPrefix(updates.Prefix)
	} else {
		upd = upd.ClearPrefix()
	}
	if updates.DateFormat != "" {
		upd = upd.SetDateFormat(updates.DateFormat)
	} else {
		upd = upd.ClearDateFormat()
	}
	_, err := upd.Save(ctx)
	return err
}

// ResetCounter resets the counter to 0 (admin only — caller must enforce authorization).
func (s *Service) ResetCounter(ctx context.Context, tenantID uuid.UUID, docType string) error {
	now := time.Now()
	_, err := s.ent.DocumentSequence.Update().
		Where(entdocseq.TenantID(tenantID), entdocseq.DocType(docType)).
		SetCurrentVal(0).
		SetLastReset(now).
		Save(ctx)
	return err
}

// atomicIncrement uses a raw SQL SELECT FOR UPDATE to safely increment the counter.
func (s *Service) atomicIncrement(ctx context.Context, tenantID uuid.UUID, docType string) (string, error) {
	tx, err := s.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return "", fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	var (
		seqID      uuid.UUID
		prefix     sql.NullString
		separator  string
		dateFormat sql.NullString
		padding    int
		resetFreq  string
		currentVal int64
		lastReset  sql.NullTime
	)

	row := tx.QueryRowContext(ctx,
		`SELECT id, prefix, separator, date_format, padding, reset_freq, current_val, last_reset
		 FROM document_sequences
		 WHERE tenant_id = $1 AND doc_type = $2
		 FOR UPDATE NOWAIT`,
		tenantID, docType,
	)
	if err := row.Scan(&seqID, &prefix, &separator, &dateFormat, &padding, &resetFreq, &currentVal, &lastReset); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			if createErr := s.seedInTx(ctx, tx, tenantID, docType); createErr != nil {
				return "", fmt.Errorf("seed sequence: %w", createErr)
			}
			row = tx.QueryRowContext(ctx,
				`SELECT id, prefix, separator, date_format, padding, reset_freq, current_val, last_reset
				 FROM document_sequences
				 WHERE tenant_id = $1 AND doc_type = $2
				 FOR UPDATE NOWAIT`,
				tenantID, docType,
			)
			if scanErr := row.Scan(&seqID, &prefix, &separator, &dateFormat, &padding, &resetFreq, &currentVal, &lastReset); scanErr != nil {
				return "", fmt.Errorf("re-scan after seed: %w", scanErr)
			}
		} else {
			return "", fmt.Errorf("select for update: %w", err)
		}
	}

	now := time.Now()

	needReset := false
	if lastReset.Valid {
		switch resetFreq {
		case "daily":
			needReset = !sameDay(lastReset.Time, now)
		case "monthly":
			needReset = !sameMonth(lastReset.Time, now)
		case "yearly":
			needReset = !sameYear(lastReset.Time, now)
		}
	}
	if needReset {
		currentVal = 0
	}

	nextVal := currentVal + 1

	if needReset {
		_, err = tx.ExecContext(ctx,
			`UPDATE document_sequences SET current_val = $1, last_reset = $2, updated_at = NOW() WHERE id = $3`,
			nextVal, now, seqID,
		)
	} else {
		_, err = tx.ExecContext(ctx,
			`UPDATE document_sequences SET current_val = $1, updated_at = NOW() WHERE id = $2`,
			nextVal, seqID,
		)
	}
	if err != nil {
		return "", fmt.Errorf("update counter: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return "", fmt.Errorf("commit: %w", err)
	}

	cfg := Config{
		Prefix:    prefix.String,
		Separator: separator,
		DateFormat: func() string {
			if dateFormat.Valid {
				return dateFormat.String
			}
			return ""
		}(),
		Padding:   padding,
		ResetFreq: resetFreq,
	}
	return formatNumber(cfg, nextVal, now), nil
}

// seedInTx inserts the default config within an existing transaction.
func (s *Service) seedInTx(ctx context.Context, tx *sql.Tx, tenantID uuid.UUID, docType string) error {
	def, ok := defaults[docType]
	if !ok {
		def = Config{Prefix: "DOC", Separator: "-", DateFormat: "YYMMDD", Padding: 6, ResetFreq: "never"}
	}
	id := uuid.New()
	_, err := tx.ExecContext(ctx,
		`INSERT INTO document_sequences (id, tenant_id, doc_type, prefix, separator, date_format, padding, reset_freq, current_val, created_at, updated_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 0, NOW(), NOW())
		 ON CONFLICT (tenant_id, doc_type) DO NOTHING`,
		id, tenantID, docType, nullableString(def.Prefix), def.Separator, nullableString(def.DateFormat), def.Padding, def.ResetFreq,
	)
	return err
}

// getOrCreateConfig retrieves or seeds the sequence config (without incrementing).
func (s *Service) getOrCreateConfig(ctx context.Context, tenantID uuid.UUID, docType string) (*Config, error) {
	seq, err := s.ent.DocumentSequence.Query().
		Where(entdocseq.TenantID(tenantID), entdocseq.DocType(docType)).
		Only(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return nil, fmt.Errorf("get sequence: %w", err)
	}
	if ent.IsNotFound(err) {
		def, ok := defaults[docType]
		if !ok {
			def = Config{Prefix: "DOC", Separator: "-", DateFormat: "YYMMDD", Padding: 6, ResetFreq: "never"}
		}
		b := s.ent.DocumentSequence.Create().
			SetTenantID(tenantID).
			SetDocType(docType).
			SetSeparator(def.Separator).
			SetPadding(def.Padding).
			SetResetFreq(def.ResetFreq).
			SetCurrentVal(0)
		if def.Prefix != "" {
			b = b.SetPrefix(def.Prefix)
		}
		if def.DateFormat != "" {
			b = b.SetDateFormat(def.DateFormat)
		}
		seq, err = b.Save(ctx)
		if err != nil {
			seq, err = s.ent.DocumentSequence.Query().
				Where(entdocseq.TenantID(tenantID), entdocseq.DocType(docType)).
				Only(ctx)
			if err != nil {
				return nil, fmt.Errorf("create/get sequence: %w", err)
			}
		}
	}
	cfg := &Config{
		Prefix:     seq.Prefix,
		Separator:  seq.Separator,
		DateFormat: seq.DateFormat,
		Padding:    seq.Padding,
		ResetFreq:  seq.ResetFreq,
		CurrentVal: seq.CurrentVal,
	}
	if seq.LastReset != nil {
		cfg.LastReset = seq.LastReset
	}
	return cfg, nil
}

// formatNumber builds the document number string: [prefix][sep][date][sep][padded_counter]
func formatNumber(cfg Config, val int64, now time.Time) string {
	sep := cfg.Separator
	var parts []string
	if cfg.Prefix != "" {
		parts = append(parts, cfg.Prefix)
	}
	if cfg.DateFormat != "" {
		parts = append(parts, formatDate(cfg.DateFormat, now))
	}
	parts = append(parts, fmt.Sprintf("%0*d", cfg.Padding, val))
	result := parts[0]
	for _, p := range parts[1:] {
		result += sep + p
	}
	return result
}

func formatDate(format string, t time.Time) string {
	switch format {
	case "YYYYMMDD":
		return t.Format("20060102")
	case "YYMMDD":
		return t.Format("060102")
	case "MMYY":
		return t.Format("0106")
	case "DDMMYY":
		return t.Format("020106")
	default:
		return t.Format("060102")
	}
}

func sameDay(a, b time.Time) bool {
	ay, am, ad := a.Date()
	by, bm, bd := b.Date()
	return ay == by && am == bm && ad == bd
}

func sameMonth(a, b time.Time) bool {
	ay, am, _ := a.Date()
	by, bm, _ := b.Date()
	return ay == by && am == bm
}

func sameYear(a, b time.Time) bool {
	return a.Year() == b.Year()
}

func nullableString(s string) sql.NullString {
	if s == "" {
		return sql.NullString{}
	}
	return sql.NullString{String: s, Valid: true}
}
