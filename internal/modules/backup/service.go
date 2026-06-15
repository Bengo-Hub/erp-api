// Package backup produces TENANT-SCOPED logical exports of erp's own data. A backup
// contains only the requesting tenant's rows (every erp table that carries tenant_id),
// gzipped JSON, stored under a per-tenant media path. It is NEVER a platform-wide DB
// dump — see memory feedback_tenant_scoped_backups. Designed to be extracted into a
// shared lib once a second service adopts it.
package backup

import (
	"compress/gzip"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"
)

// Service generates + serves tenant-scoped backups from the local media root.
type Service struct {
	db   *sql.DB
	root string // {MEDIA_ROOT}/backups
	log  *zap.Logger
}

func NewService(db *sql.DB, mediaRoot string, log *zap.Logger) *Service {
	return &Service{db: db, root: filepath.Join(mediaRoot, "backups"), log: log.Named("backup.Service")}
}

// Info describes one stored backup artifact.
type Info struct {
	Name      string    `json:"name"`
	Size      int64     `json:"size"`
	CreatedAt time.Time `json:"created_at"`
}

func (s *Service) tenantDir(tenantID uuid.UUID) string {
	return filepath.Join(s.root, tenantID.String())
}

// tenantScopedTables lists public tables that carry a tenant_id column.
func (s *Service) tenantScopedTables(ctx context.Context) ([]string, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT table_name FROM information_schema.columns
		 WHERE table_schema = 'public' AND column_name = 'tenant_id'
		 ORDER BY table_name`)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	var tables []string
	for rows.Next() {
		var t string
		if err := rows.Scan(&t); err != nil {
			return nil, err
		}
		tables = append(tables, t)
	}
	return tables, rows.Err()
}

// Generate writes a gzipped JSON export of the tenant's rows and returns its filename.
func (s *Service) Generate(ctx context.Context, tenantID uuid.UUID) (Info, error) {
	tables, err := s.tenantScopedTables(ctx)
	if err != nil {
		return Info{}, fmt.Errorf("discover tables: %w", err)
	}

	export := map[string]any{
		"service":      "erp",
		"tenant_id":    tenantID.String(),
		"generated_at": time.Now().UTC().Format(time.RFC3339),
		"tables":       map[string]json.RawMessage{},
	}
	tableData := export["tables"].(map[string]json.RawMessage)
	for _, t := range tables {
		// Identifier is from information_schema (not user input); quote defensively.
		q := fmt.Sprintf(`SELECT coalesce(json_agg(row_to_json(x)), '[]'::json) FROM %q x WHERE tenant_id = $1`, t)
		var raw []byte
		if err := s.db.QueryRowContext(ctx, q, tenantID).Scan(&raw); err != nil {
			s.log.Warn("backup: dump table failed (skipped)", zap.String("table", t), zap.Error(err))
			continue
		}
		tableData[t] = raw
	}

	dir := s.tenantDir(tenantID)
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return Info{}, fmt.Errorf("mkdir: %w", err)
	}
	name := fmt.Sprintf("erp_backup_%s.json.gz", time.Now().UTC().Format("20060102_150405"))
	path := filepath.Join(dir, name)

	f, err := os.Create(path)
	if err != nil {
		return Info{}, fmt.Errorf("create: %w", err)
	}
	defer func() { _ = f.Close() }()
	gz := gzip.NewWriter(f)
	if err := json.NewEncoder(gz).Encode(export); err != nil {
		_ = gz.Close()
		_ = os.Remove(path)
		return Info{}, fmt.Errorf("encode: %w", err)
	}
	if err := gz.Close(); err != nil {
		_ = os.Remove(path)
		return Info{}, fmt.Errorf("gzip close: %w", err)
	}
	st, _ := f.Stat()
	s.log.Info("tenant backup generated", zap.String("tenant", tenantID.String()), zap.String("file", name))
	return Info{Name: name, Size: sizeOf(st), CreatedAt: time.Now().UTC()}, nil
}

// List returns the tenant's backups, newest first.
func (s *Service) List(ctx context.Context, tenantID uuid.UUID) ([]Info, error) {
	entries, err := os.ReadDir(s.tenantDir(tenantID))
	if os.IsNotExist(err) {
		return []Info{}, nil
	}
	if err != nil {
		return nil, err
	}
	out := make([]Info, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		fi, err := e.Info()
		if err != nil {
			continue
		}
		out = append(out, Info{Name: e.Name(), Size: fi.Size(), CreatedAt: fi.ModTime().UTC()})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt.After(out[j].CreatedAt) })
	return out, nil
}

// Open returns a reader for one of the tenant's backups, rejecting path traversal and
// any name that does not resolve INSIDE that tenant's own backup directory.
func (s *Service) Open(tenantID uuid.UUID, name string) (io.ReadCloser, error) {
	if name == "" || name != filepath.Base(name) || strings.Contains(name, "..") {
		return nil, fmt.Errorf("invalid backup name")
	}
	dir := s.tenantDir(tenantID)
	path := filepath.Join(dir, name)
	if !strings.HasPrefix(filepath.Clean(path), filepath.Clean(dir)+string(os.PathSeparator)) {
		return nil, fmt.Errorf("invalid backup path")
	}
	return os.Open(path)
}

// Delete removes one of the tenant's backups (same ownership guard as Open).
func (s *Service) Delete(tenantID uuid.UUID, name string) error {
	if name == "" || name != filepath.Base(name) || strings.Contains(name, "..") {
		return fmt.Errorf("invalid backup name")
	}
	return os.Remove(filepath.Join(s.tenantDir(tenantID), name))
}

func sizeOf(st os.FileInfo) int64 {
	if st == nil {
		return 0
	}
	return st.Size()
}
