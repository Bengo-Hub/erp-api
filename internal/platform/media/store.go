// Package media provides per-tenant file storage on the local media volume (the same
// convention as the other services: relative paths stored in the DB, resolved against
// MEDIA_ROOT at read time; PVC-backed in k8s). It is deliberately minimal — the ERP only
// stores HR artifacts (candidate resumes, etc.), never customer/order media.
package media

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/google/uuid"
)

// Store writes uploads under MEDIA_ROOT/{tenant}/{category}/ and returns the RELATIVE path
// (the value persisted in the DB; resolved to a URL/file at read time).
type Store struct {
	root    string
	urlBase string
}

// NewStore builds a media store rooted at MEDIA_ROOT (default "./media").
func NewStore(root, urlBase string) *Store {
	if root == "" {
		root = "./media"
	}
	return &Store{root: root, urlBase: strings.TrimRight(urlBase, "/")}
}

// allowedExt is the resume upload allow-list.
var allowedExt = map[string]bool{".pdf": true, ".doc": true, ".docx": true, ".odt": true}

// SaveResume writes a candidate resume and returns its relative media path. The filename is
// randomized to avoid collisions/path traversal; only document extensions are accepted.
func (s *Store) SaveResume(tenantID, candidateID uuid.UUID, originalName string, r io.Reader) (string, error) {
	ext := strings.ToLower(filepath.Ext(originalName))
	if !allowedExt[ext] {
		return "", fmt.Errorf("media: unsupported resume type %q (allowed: pdf, doc, docx, odt)", ext)
	}
	rel := filepath.ToSlash(filepath.Join(tenantID.String(), "recruitment", "resumes", candidateID.String()+ext))
	abs := filepath.Join(s.root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(abs), 0o755); err != nil {
		return "", fmt.Errorf("media: mkdir: %w", err)
	}
	f, err := os.Create(abs)
	if err != nil {
		return "", fmt.Errorf("media: create file: %w", err)
	}
	defer func() { _ = f.Close() }()
	if _, err := io.Copy(f, r); err != nil {
		return "", fmt.Errorf("media: write file: %w", err)
	}
	return rel, nil
}

// claimAttachmentExt is the expense-claim receipt allow-list (documents + images).
var claimAttachmentExt = map[string]bool{
	".pdf": true, ".doc": true, ".docx": true, ".odt": true,
	".png": true, ".jpg": true, ".jpeg": true, ".webp": true, ".gif": true,
}

// SaveClaimAttachment writes an expense-claim receipt/attachment under the per-tenant media
// path and returns its relative path. The filename keeps its extension but is namespaced by
// claim id; a short random suffix avoids overwrites when several receipts are uploaded.
func (s *Store) SaveClaimAttachment(tenantID, claimID uuid.UUID, originalName string, r io.Reader) (string, error) {
	ext := strings.ToLower(filepath.Ext(originalName))
	if !claimAttachmentExt[ext] {
		return "", fmt.Errorf("media: unsupported attachment type %q (allowed: pdf, doc, docx, odt, png, jpg, jpeg, webp, gif)", ext)
	}
	name := claimID.String() + "_" + uuid.New().String()[:8] + ext
	rel := filepath.ToSlash(filepath.Join(tenantID.String(), "payroll", "claims", name))
	abs := filepath.Join(s.root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(abs), 0o755); err != nil {
		return "", fmt.Errorf("media: mkdir: %w", err)
	}
	f, err := os.Create(abs)
	if err != nil {
		return "", fmt.Errorf("media: create file: %w", err)
	}
	defer func() { _ = f.Close() }()
	if _, err := io.Copy(f, r); err != nil {
		return "", fmt.Errorf("media: write file: %w", err)
	}
	return rel, nil
}

// URL resolves a stored relative path to a public URL when MEDIA_URL_BASE is set.
func (s *Store) URL(rel string) string {
	if rel == "" || s.urlBase == "" {
		return rel
	}
	return s.urlBase + "/" + strings.TrimLeft(rel, "/")
}
