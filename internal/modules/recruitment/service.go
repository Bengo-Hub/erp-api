// Package recruitment implements tenant-isolated recruitment: job postings, candidates,
// applications (hiring-pipeline FSM), and employee onboarding (checklist seeded on hire).
package recruitment

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/application"
	"github.com/Bengo-Hub/erp-api/internal/ent/candidate"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobposting"
)

// Service holds recruitment CRUD + the application FSM + onboarding seeding. Tenant-scoped.
type Service struct {
	orm *ent.Client
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// ---- Job postings ----

// ListPostings returns tenant-scoped postings (optionally by status).
func (s *Service) ListPostings(ctx context.Context, tenantID uuid.UUID, status string) ([]*ent.JobPosting, error) {
	q := s.orm.JobPosting.Query().Where(jobposting.TenantID(tenantID))
	if status != "" {
		q = q.Where(jobposting.StatusEQ(jobposting.Status(status)))
	}
	return q.Order(ent.Desc(jobposting.FieldPostedAt)).All(ctx)
}

// PostingInput is the create payload for a job posting.
type PostingInput struct {
	Title       string
	Description string
	Department  string
	Location    string
	Status      string
}

// CreatePosting inserts a tenant-scoped job posting.
func (s *Service) CreatePosting(ctx context.Context, tenantID uuid.UUID, in PostingInput) (*ent.JobPosting, error) {
	status := in.Status
	if status == "" {
		status = "draft"
	}
	b := s.orm.JobPosting.Create().
		SetTenantID(tenantID).SetTitle(in.Title).SetDescription(in.Description).
		SetStatus(jobposting.Status(status))
	if in.Department != "" {
		b = b.SetDepartment(in.Department)
	}
	if in.Location != "" {
		b = b.SetLocation(in.Location)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: create posting: %w", err)
	}
	return row, nil
}

// SetPostingStatus updates a posting's status, stamping closed_at when moving to closed.
func (s *Service) SetPostingStatus(ctx context.Context, tenantID, id uuid.UUID, status string) (*ent.JobPosting, error) {
	p, err := s.orm.JobPosting.Query().Where(jobposting.TenantID(tenantID), jobposting.ID(id)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: load posting: %w", err)
	}
	u := p.Update().SetStatus(jobposting.Status(status))
	if status == "closed" {
		u = u.SetClosedAt(time.Now().UTC())
	}
	return u.Save(ctx)
}

// ---- Candidates ----

// ListCandidates returns tenant-scoped candidates.
func (s *Service) ListCandidates(ctx context.Context, tenantID uuid.UUID) ([]*ent.Candidate, error) {
	return s.orm.Candidate.Query().
		Where(candidate.TenantID(tenantID)).
		Order(ent.Desc(candidate.FieldCreatedAt)).All(ctx)
}

// CandidateInput is the create payload for a candidate.
type CandidateInput struct {
	FullName  string
	Email     string
	Phone     string
	ResumeURL string
}

// CreateCandidate inserts a tenant-scoped candidate.
func (s *Service) CreateCandidate(ctx context.Context, tenantID uuid.UUID, in CandidateInput) (*ent.Candidate, error) {
	b := s.orm.Candidate.Create().
		SetTenantID(tenantID).SetFullName(in.FullName).SetEmail(in.Email)
	if in.Phone != "" {
		b = b.SetPhone(in.Phone)
	}
	if in.ResumeURL != "" {
		b = b.SetResumeURL(in.ResumeURL)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: create candidate: %w", err)
	}
	return row, nil
}

// GetCandidate loads one tenant-scoped candidate.
func (s *Service) GetCandidate(ctx context.Context, tenantID, id uuid.UUID) (*ent.Candidate, error) {
	return s.orm.Candidate.Query().Where(candidate.TenantID(tenantID), candidate.ID(id)).Only(ctx)
}

// SetCandidateResume stores the relative media path of an uploaded resume on a candidate.
func (s *Service) SetCandidateResume(ctx context.Context, tenantID, id uuid.UUID, resumePath string) (*ent.Candidate, error) {
	n, err := s.orm.Candidate.Update().
		Where(candidate.TenantID(tenantID), candidate.ID(id)).
		SetResumeURL(resumePath).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: set resume: %w", err)
	}
	if n == 0 {
		return nil, fmt.Errorf("recruitment: candidate not found")
	}
	return s.GetCandidate(ctx, tenantID, id)
}

// ---- Applications ----

// ListApplications returns applications filtered by tenant (+ optional job/status).
func (s *Service) ListApplications(ctx context.Context, tenantID uuid.UUID, jobID *uuid.UUID, status string) ([]*ent.Application, error) {
	q := s.orm.Application.Query().Where(application.TenantID(tenantID))
	if jobID != nil {
		q = q.Where(application.JobID(*jobID))
	}
	if status != "" {
		q = q.Where(application.StatusEQ(application.Status(status)))
	}
	return q.Order(ent.Desc(application.FieldAppliedAt)).All(ctx)
}

// CreateApplication files a candidate's application (starts at applied).
func (s *Service) CreateApplication(ctx context.Context, tenantID, jobID, candidateID uuid.UUID, notes string) (*ent.Application, error) {
	b := s.orm.Application.Create().
		SetTenantID(tenantID).SetJobID(jobID).SetCandidateID(candidateID).
		SetStatus(application.StatusApplied)
	if notes != "" {
		b = b.SetNotes(notes)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: create application: %w", err)
	}
	return row, nil
}
