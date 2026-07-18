package employees

import (
	"context"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeedocument"
)

// This file adds employee HR-document management (the EmployeeDocument ent model): the
// relative media path is saved by the handler via the media store, and the row is created
// here. All queries are tenant-isolated.

// DocumentInput is the create payload for an employee document. FileURL is the relative media
// path returned by the media store (resolved to a URL/bytes at read time).
type DocumentInput struct {
	EmployeeID   uuid.UUID
	Title        string
	DocumentType string
	FileURL      string
}

// CreateDocument records an uploaded HR document for a tenant-scoped employee.
func (s *Service) CreateDocument(ctx context.Context, tenantID uuid.UUID, in DocumentInput) (*ent.EmployeeDocument, error) {
	if strings.TrimSpace(in.Title) == "" {
		return nil, fmt.Errorf("employees: document title is required")
	}
	if err := s.ownsEmployee(ctx, tenantID, in.EmployeeID); err != nil {
		return nil, err
	}
	b := s.orm.EmployeeDocument.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetTitle(in.Title)
	if in.DocumentType != "" {
		b = b.SetDocumentType(in.DocumentType)
	}
	if in.FileURL != "" {
		b = b.SetFileURL(in.FileURL)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("employees: create document: %w", err)
	}
	return row, nil
}

// ListDocuments returns a tenant-scoped employee's documents, newest first.
func (s *Service) ListDocuments(ctx context.Context, tenantID, employeeID uuid.UUID) ([]*ent.EmployeeDocument, error) {
	return s.orm.EmployeeDocument.Query().
		Where(employeedocument.TenantID(tenantID), employeedocument.EmployeeID(employeeID)).
		Order(ent.Desc(employeedocument.FieldCreatedAt)).
		All(ctx)
}

// GetDocument fetches one tenant-scoped employee document (scoped to the owning employee).
func (s *Service) GetDocument(ctx context.Context, tenantID, employeeID, docID uuid.UUID) (*ent.EmployeeDocument, error) {
	return s.orm.EmployeeDocument.Query().
		Where(
			employeedocument.TenantID(tenantID),
			employeedocument.EmployeeID(employeeID),
			employeedocument.ID(docID),
		).
		Only(ctx)
}
