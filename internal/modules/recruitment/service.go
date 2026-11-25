// Package recruitment implements tenant-isolated recruitment: job postings, candidates,
// applications (hiring-pipeline FSM), and employee onboarding (checklist seeded on hire).
package recruitment

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/application"
	"github.com/Bengo-Hub/erp-api/internal/ent/candidate"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobposting"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
	"github.com/Bengo-Hub/erp-api/internal/platform/tenantref"
)

// Service holds recruitment CRUD + the application FSM + onboarding seeding. Tenant-scoped.
type Service struct {
	orm    *ent.Client
	notify *events.Notifications // optional: candidate emails on apply/transition
	// staffNumbers issues staff numbers for employees created on hire (optional).
	staffNumbers employees.StaffNumberer
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// WithNotifier wires the outbox notifications emitter so the careers portal + hiring pipeline can
// email candidates (application received, status updates, hire). Optional — nil = no emails.
func (s *Service) WithNotifier(n *events.Notifications) *Service {
	s.notify = n
	return s
}

// emailCandidate sends a best-effort plain-text email to a candidate (never fails the caller).
func (s *Service) emailCandidate(ctx context.Context, tenantID uuid.UUID, aggregateID, to, subject, body string) {
	if s.notify == nil || to == "" {
		return
	}
	_ = s.notify.RequestEmail(ctx, tenantID, aggregateID, events.EmailRequest{
		To: []string{to}, Subject: subject, Body: body,
	})
}

// ---- Job postings ----

// ListPostings returns tenant-scoped postings (optionally by status).
func (s *Service) ListPostings(ctx context.Context, tenantID uuid.UUID, status string) ([]*ent.JobPosting, error) {
	q := s.orm.JobPosting.Query().Where(jobposting.TenantID(tenantID))
	if status != "" {
		q = q.Where(jobposting.StatusEQ(jobposting.Status(status)))
	}
	return q.Order(ent.Desc(jobposting.FieldPostedAt)).All(ctx)
}

// PostingInput is the create/update payload for a job posting.
type PostingInput struct {
	Title               string
	Description         string
	Requirements        string
	Responsibilities    string
	SalaryMin           string
	SalaryMax           string
	SalaryCurrency      string
	Department          string
	Location            string
	Status              string
	IsPublic            bool
	EmploymentType      string
	NumPositions        int
	ApplicationDeadline *time.Time
}

// applyOptional sets the nullable rich-text / salary fields shared by create & update.
// Empty strings clear the column (so editing a field to blank persists as NULL).
func applyPostingOptional[B interface {
	SetNillableRequirements(*string) B
	SetNillableResponsibilities(*string) B
	SetNillableSalaryMin(*string) B
	SetNillableSalaryMax(*string) B
	SetNillableSalaryCurrency(*string) B
}](b B, in PostingInput) B {
	ptr := func(v string) *string {
		if v == "" {
			return nil
		}
		return &v
	}
	return b.
		SetNillableRequirements(ptr(in.Requirements)).
		SetNillableResponsibilities(ptr(in.Responsibilities)).
		SetNillableSalaryMin(ptr(in.SalaryMin)).
		SetNillableSalaryMax(ptr(in.SalaryMax)).
		SetNillableSalaryCurrency(ptr(in.SalaryCurrency))
}

// CreatePosting inserts a tenant-scoped job posting with a unique public slug.
func (s *Service) CreatePosting(ctx context.Context, tenantID uuid.UUID, in PostingInput) (*ent.JobPosting, error) {
	status := in.Status
	if status == "" {
		status = "draft"
	}
	slug, err := s.uniquePostingSlug(ctx, tenantID, in.Title, uuid.Nil)
	if err != nil {
		return nil, err
	}
	b := s.orm.JobPosting.Create().
		SetTenantID(tenantID).SetTitle(in.Title).SetDescription(in.Description).
		SetStatus(jobposting.Status(status)).SetSlug(slug).SetIsPublic(in.IsPublic)
	if in.Department != "" {
		b = b.SetDepartment(in.Department)
	}
	if in.Location != "" {
		b = b.SetLocation(in.Location)
	}
	if in.EmploymentType != "" {
		b = b.SetEmploymentType(in.EmploymentType)
	}
	if in.NumPositions > 0 {
		b = b.SetNumPositions(in.NumPositions)
	}
	if in.ApplicationDeadline != nil {
		b = b.SetApplicationDeadline(*in.ApplicationDeadline)
	}
	b = applyPostingOptional(b, in)
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: create posting: %w", err)
	}
	return row, nil
}

// UpdatePosting edits a posting's editable fields (title/description/location/employment/visibility/
// deadline). The slug is regenerated only when the title changes (keeps public links stable otherwise).
func (s *Service) UpdatePosting(ctx context.Context, tenantID, id uuid.UUID, in PostingInput) (*ent.JobPosting, error) {
	p, err := s.orm.JobPosting.Query().Where(jobposting.TenantID(tenantID), jobposting.ID(id)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: load posting: %w", err)
	}
	u := p.Update().
		SetTitle(in.Title).SetDescription(in.Description).SetIsPublic(in.IsPublic)
	if in.Department != "" {
		u = u.SetDepartment(in.Department)
	}
	if in.Location != "" {
		u = u.SetLocation(in.Location)
	}
	if in.EmploymentType != "" {
		u = u.SetEmploymentType(in.EmploymentType)
	}
	if in.NumPositions > 0 {
		u = u.SetNumPositions(in.NumPositions)
	}
	if in.ApplicationDeadline != nil {
		u = u.SetApplicationDeadline(*in.ApplicationDeadline)
	}
	if in.Status != "" && in.Status != string(p.Status) {
		u = u.SetStatus(jobposting.Status(in.Status))
		if in.Status == "closed" {
			u = u.SetClosedAt(time.Now().UTC())
		}
	}
	u = applyPostingOptional(u, in)
	if in.Title != p.Title {
		slug, err := s.uniquePostingSlug(ctx, tenantID, in.Title, id)
		if err != nil {
			return nil, err
		}
		u = u.SetSlug(slug)
	}
	return u.Save(ctx)
}

// ErrPostingInUse is returned when a posting with applications is deleted.
var ErrPostingInUse = errors.New("this posting has applications; close it instead")

// DeletePosting removes a posting nobody has applied to (ErrPostingInUse otherwise).
func (s *Service) DeletePosting(ctx context.Context, tenantID, id uuid.UUID) error {
	p, err := s.orm.JobPosting.Query().Where(jobposting.TenantID(tenantID), jobposting.ID(id)).Only(ctx)
	if err != nil {
		return err
	}
	used, err := s.orm.Application.Query().
		Where(application.TenantID(tenantID), application.JobID(p.ID)).Exist(ctx)
	if err != nil {
		return fmt.Errorf("recruitment: check applications: %w", err)
	}
	if used {
		return ErrPostingInUse
	}
	return s.orm.JobPosting.DeleteOne(p).Exec(ctx)
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

// CandidateInput is the create/update payload for a candidate. Source and Status have no
// columns; they are kept in the candidate metadata.
type CandidateInput struct {
	FullName  string
	Email     string
	Phone     string
	ResumeURL string
	Source    string
	Status    string
}

// CandidateStatuses are the candidate states the screens offer. Where an application
// stands in the pipeline is the application's own status.
var CandidateStatuses = []string{"new", "active", "on_hold", "withdrawn", "hired"}

func (in CandidateInput) validate() error {
	if strings.TrimSpace(in.FullName) == "" {
		return fmt.Errorf("recruitment: full_name is required")
	}
	if in.Status != "" && !slices.Contains(CandidateStatuses, in.Status) {
		return fmt.Errorf("recruitment: status must be one of %s", strings.Join(CandidateStatuses, ", "))
	}
	return nil
}

// metadata merges source and status into existing metadata (a blank source removes it).
func (in CandidateInput) metadata(existing map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range existing {
		out[k] = v
	}
	if src := strings.TrimSpace(in.Source); src != "" {
		out["source"] = src
	} else {
		delete(out, "source")
	}
	status := in.Status
	if status == "" {
		status = "new"
	}
	out["status"] = status
	return out
}

// CandidateView is a candidate with its metadata fields at the top level.
type CandidateView struct {
	*ent.Candidate
	Source string `json:"source,omitempty"`
	Status string `json:"status"`
}

// ViewCandidate flattens a candidate's metadata.
func ViewCandidate(c *ent.Candidate) CandidateView {
	v := CandidateView{Candidate: c, Status: "new"}
	if s, ok := c.Metadata["source"].(string); ok {
		v.Source = s
	}
	if s, ok := c.Metadata["status"].(string); ok && s != "" {
		v.Status = s
	}
	return v
}

// CreateCandidate inserts a tenant-scoped candidate.
func (s *Service) CreateCandidate(ctx context.Context, tenantID uuid.UUID, in CandidateInput) (*ent.Candidate, error) {
	if err := in.validate(); err != nil {
		return nil, err
	}
	b := s.orm.Candidate.Create().
		SetTenantID(tenantID).SetFullName(strings.TrimSpace(in.FullName)).SetEmail(in.Email).
		SetMetadata(in.metadata(nil))
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

// UpdateCandidate changes a candidate's name, contacts, source and status. The resume is
// changed through UploadResume, so an empty ResumeURL keeps the stored one.
func (s *Service) UpdateCandidate(ctx context.Context, tenantID, id uuid.UUID, in CandidateInput) (*ent.Candidate, error) {
	if err := in.validate(); err != nil {
		return nil, err
	}
	c, err := s.GetCandidate(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	u := c.Update().SetFullName(strings.TrimSpace(in.FullName)).SetEmail(in.Email).
		SetMetadata(in.metadata(c.Metadata))
	if in.Phone != "" {
		u = u.SetPhone(in.Phone)
	} else {
		u = u.ClearPhone()
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: update candidate: %w", err)
	}
	return row, nil
}

// ErrCandidateInUse is returned when a candidate with applications is deleted.
var ErrCandidateInUse = errors.New("this candidate has applications; reject or delete them first, or mark the candidate withdrawn")

// DeleteCandidate removes a candidate who has no applications (ErrCandidateInUse otherwise)
// and returns the removed row, so the caller can release its stored resume.
func (s *Service) DeleteCandidate(ctx context.Context, tenantID, id uuid.UUID) (*ent.Candidate, error) {
	c, err := s.GetCandidate(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	used, err := s.orm.Application.Query().
		Where(application.TenantID(tenantID), application.CandidateID(c.ID)).Exist(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: check applications: %w", err)
	}
	if used {
		return nil, ErrCandidateInUse
	}
	if err := s.orm.Candidate.DeleteOne(c).Exec(ctx); err != nil {
		return nil, fmt.Errorf("recruitment: delete candidate: %w", err)
	}
	return c, nil
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

// ApplicationView is an application with the candidate's name and email and the job title.
type ApplicationView struct {
	*ent.Application
	CandidateName  string `json:"candidate_name,omitempty"`
	CandidateEmail string `json:"candidate_email,omitempty"`
	JobTitle       string `json:"job_title,omitempty"`
}

// DescribeApplications adds candidate and job names to applications (one query per kind).
func (s *Service) DescribeApplications(ctx context.Context, tenantID uuid.UUID, rows []*ent.Application) ([]ApplicationView, error) {
	out := make([]ApplicationView, len(rows))
	if len(rows) == 0 {
		return out, nil
	}
	candIDs := make([]uuid.UUID, len(rows))
	jobIDs := make([]uuid.UUID, len(rows))
	for i, a := range rows {
		candIDs[i], jobIDs[i] = a.CandidateID, a.JobID
	}
	cands, err := s.orm.Candidate.Query().Where(candidate.TenantID(tenantID), candidate.IDIn(candIDs...)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: load candidates: %w", err)
	}
	jobs, err := s.orm.JobPosting.Query().Where(jobposting.TenantID(tenantID), jobposting.IDIn(jobIDs...)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: load postings: %w", err)
	}
	byCand := make(map[uuid.UUID]*ent.Candidate, len(cands))
	for _, c := range cands {
		byCand[c.ID] = c
	}
	titles := make(map[uuid.UUID]string, len(jobs))
	for _, j := range jobs {
		titles[j.ID] = j.Title
	}
	for i, a := range rows {
		v := ApplicationView{Application: a, JobTitle: titles[a.JobID]}
		if c := byCand[a.CandidateID]; c != nil {
			v.CandidateName, v.CandidateEmail = c.FullName, c.Email
		}
		out[i] = v
	}
	return out, nil
}

// CreateApplication files a candidate's application (starts at applied).
func (s *Service) CreateApplication(ctx context.Context, tenantID, jobID, candidateID uuid.UUID, notes string) (*ent.Application, error) {
	if err := tenantref.Require(ctx, "job posting", s.orm.JobPosting.Query().
		Where(jobposting.TenantID(tenantID), jobposting.ID(jobID))); err != nil {
		return nil, err
	}
	if err := tenantref.Require(ctx, "candidate", s.orm.Candidate.Query().
		Where(candidate.TenantID(tenantID), candidate.ID(candidateID))); err != nil {
		return nil, err
	}
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
