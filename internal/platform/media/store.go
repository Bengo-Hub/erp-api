// Package media keeps the ERP's HR files (candidate resumes, expense-claim receipts, employee
// documents) on the shared object storage (httpware/objectstore). Every file is private: rows keep
// the key, reads go through the API or a presigned link. It never stores customer or order media.
package media

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"path/filepath"
	"strings"

	"github.com/Bengo-Hub/httpware/objectstore"
	"github.com/google/uuid"
)

// Media types: erp/<tenant>/<type>/<owner id>/<uuid>.<ext>.
const (
	TypeResumes           = "resumes"
	TypeClaimAttachments  = "claim-attachments"
	TypeEmployeeDocuments = "employee-documents"
)

// maxFileBytes is the upload limit for every ERP file.
const maxFileBytes = 10 << 20

// contentTypes maps the accepted extensions to the type the file is stored with (office formats
// are not reliably sniffed, so the extension allow-list decides, as before).
var contentTypes = map[string]string{
	".pdf":  "application/pdf",
	".doc":  "application/msword",
	".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	".odt":  "application/vnd.oasis.opendocument.text",
	".png":  "image/png",
	".jpg":  "image/jpeg",
	".jpeg": "image/jpeg",
	".webp": "image/webp",
	".gif":  "image/gif",
}

var documentExt = []string{".pdf", ".doc", ".docx", ".odt"}

var allowedExt = map[string][]string{
	TypeResumes:           documentExt,
	TypeClaimAttachments:  append(append([]string{}, documentExt...), ".png", ".jpg", ".jpeg", ".webp", ".gif"),
	TypeEmployeeDocuments: append(append([]string{}, documentExt...), ".png", ".jpg", ".jpeg", ".webp", ".gif"),
}

// RegisterMediaTypes sets the ERP's media rules on the shared registry. Call once at startup.
func RegisterMediaTypes() {
	for name := range allowedExt {
		// Image: JPEG and PNG uploads are re-encoded; the extension allow-list below decides the rest.
		objectstore.Register(objectstore.MediaType{Name: name, MaxBytes: maxFileBytes, Image: true})
	}
}

// Store writes and reads the ERP's files.
type Store struct {
	s *objectstore.Store
}

// NewStore wraps the service's object store.
func NewStore(s *objectstore.Store) *Store { return &Store{s: s} }

// Enabled reports whether files can be stored.
func (m *Store) Enabled() bool { return m != nil && m.s.Enabled() }

// SaveResume stores a candidate resume and returns its key.
func (m *Store) SaveResume(ctx context.Context, tenantID, candidateID uuid.UUID, originalName string, r io.Reader) (string, error) {
	return m.save(ctx, TypeResumes, tenantID, candidateID, originalName, r)
}

// SaveClaimAttachment stores an expense-claim receipt and returns its key.
func (m *Store) SaveClaimAttachment(ctx context.Context, tenantID, claimID uuid.UUID, originalName string, r io.Reader) (string, error) {
	return m.save(ctx, TypeClaimAttachments, tenantID, claimID, originalName, r)
}

// SaveEmployeeDocument stores an HR employee document (an upload or a generated contract) and
// returns its key.
func (m *Store) SaveEmployeeDocument(ctx context.Context, tenantID, employeeID uuid.UUID, filename string, data []byte) (string, error) {
	return m.save(ctx, TypeEmployeeDocuments, tenantID, employeeID, filename, bytes.NewReader(data))
}

func (m *Store) save(ctx context.Context, mediaType string, tenantID, ownerID uuid.UUID, name string, r io.Reader) (string, error) {
	ext := strings.ToLower(filepath.Ext(name))
	if !contains(allowedExt[mediaType], ext) {
		return "", fmt.Errorf("media: unsupported file type %q (allowed: %s)", ext, strings.Join(allowedExt[mediaType], ", "))
	}
	data, err := io.ReadAll(io.LimitReader(r, maxFileBytes+1))
	if err != nil {
		return "", fmt.Errorf("media: read file: %w", err)
	}
	if len(data) == 0 {
		return "", fmt.Errorf("media: the file is empty")
	}
	if len(data) > maxFileBytes {
		return "", fmt.Errorf("media: the file must be at most 10 MB")
	}
	ct := contentTypes[ext]
	// JPEG and PNG are re-encoded (EXIF location removed, appended payloads dropped) with the
	// shared image rules; the bytes must really be the image the name claims.
	if ct == "image/jpeg" || ct == "image/png" {
		up, err := objectstore.Prepare(data, mediaType)
		if err != nil {
			return "", fmt.Errorf("media: %w", err)
		}
		if up.ContentType != ct {
			return "", fmt.Errorf("media: the file is not a %s image", strings.TrimPrefix(ext, "."))
		}
		data = up.Data
	}
	key, err := m.s.Key(objectstore.Owner{TenantID: tenantID.String()}, mediaType, ownerID.String(), uuid.NewString()+ext)
	if err != nil {
		return "", err
	}
	if err := m.s.Put(ctx, key, data, ct); err != nil {
		return "", fmt.Errorf("media: store file: %w", err)
	}
	return key, nil
}

// Get reads a stored file and its content type (for streaming downloads through the API).
func (m *Store) Get(ctx context.Context, key string) ([]byte, string, error) {
	if !m.s.Owned(key) {
		return nil, "", objectstore.ErrNotFound
	}
	b, ct, err := m.s.Get(ctx, key)
	if ct == "" || ct == "application/octet-stream" {
		ct = contentTypes[strings.ToLower(filepath.Ext(key))]
	}
	return b, ct, err
}

// URL is a short-lived presigned link to a stored file; any other value (an external link a
// public applicant gave) is returned as is.
func (m *Store) URL(ref string) string {
	if ref == "" || m == nil {
		return ref
	}
	return m.s.URL(ref)
}

// Release deletes a replaced file after the row points at its successor. Only this service's
// own keys are touched; errors are returned for logging only.
func (m *Store) Release(ctx context.Context, old, current string) error {
	if old == "" || old == current || !m.s.Owned(old) {
		return nil
	}
	return m.s.Delete(ctx, old)
}

func contains(list []string, v string) bool {
	for _, s := range list {
		if s == v {
			return true
		}
	}
	return false
}
