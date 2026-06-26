package recruitment

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/application"
	"github.com/Bengo-Hub/erp-api/internal/ent/authtenant"
	"github.com/Bengo-Hub/erp-api/internal/ent/candidate"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobposting"
)

var slugStrip = regexp.MustCompile(`[^a-z0-9]+`)

// slugify lowercases + hyphenates a title for use in a public URL.
func slugify(s string) string {
	out := slugStrip.ReplaceAllString(strings.ToLower(strings.TrimSpace(s)), "-")
	out = strings.Trim(out, "-")
	if out == "" {
		out = "job"
	}
	return out
}

// uniquePostingSlug returns a tenant-unique slug derived from title, suffixing -2, -3, … on
// collision (excluding the posting being updated).
func (s *Service) uniquePostingSlug(ctx context.Context, tenantID uuid.UUID, title string, excludeID uuid.UUID) (string, error) {
	base := slugify(title)
	for i := 0; ; i++ {
		candidateSlug := base
		if i > 0 {
			candidateSlug = fmt.Sprintf("%s-%d", base, i+1)
		}
		q := s.orm.JobPosting.Query().Where(jobposting.TenantID(tenantID), jobposting.Slug(candidateSlug))
		if excludeID != uuid.Nil {
			q = q.Where(jobposting.IDNEQ(excludeID))
		}
		exists, err := q.Exist(ctx)
		if err != nil {
			return "", err
		}
		if !exists {
			return candidateSlug, nil
		}
	}
}

// TenantBySlug resolves a tenant UUID from its public org slug (careers portal entry point).
func (s *Service) TenantBySlug(ctx context.Context, slug string) (uuid.UUID, error) {
	t, err := s.orm.AuthTenant.Query().Where(authtenant.Slug(slug)).Only(ctx)
	if err != nil {
		return uuid.Nil, err
	}
	return t.ID, nil
}

// PublicPostings lists the postings visible on the public careers portal (is_public + open).
func (s *Service) PublicPostings(ctx context.Context, tenantID uuid.UUID) ([]*ent.JobPosting, error) {
	return s.orm.JobPosting.Query().
		Where(jobposting.TenantID(tenantID), jobposting.IsPublic(true), jobposting.StatusEQ(jobposting.StatusOpen)).
		Order(ent.Desc(jobposting.FieldPostedAt)).All(ctx)
}

// PublicPostingBySlug returns one public, open posting by its slug.
func (s *Service) PublicPostingBySlug(ctx context.Context, tenantID uuid.UUID, slug string) (*ent.JobPosting, error) {
	return s.orm.JobPosting.Query().
		Where(jobposting.TenantID(tenantID), jobposting.Slug(slug), jobposting.IsPublic(true), jobposting.StatusEQ(jobposting.StatusOpen)).
		Only(ctx)
}

// PublicApplyInput is a public job application from the careers portal.
type PublicApplyInput struct {
	PostingSlug string
	FullName    string
	Email       string
	Phone       string
	CoverLetter string
	ResumeURL   string
}

// PublicApply records a careers-portal application: it finds the public posting, gets-or-creates a
// candidate by email, and creates the application (source=careers_portal) — deduping so the same
// email can't apply twice to the same posting. Returns the created/updated application.
func (s *Service) PublicApply(ctx context.Context, tenantID uuid.UUID, in PublicApplyInput) (*ent.Application, error) {
	if in.FullName == "" || in.Email == "" {
		return nil, fmt.Errorf("name and email are required")
	}
	post, err := s.PublicPostingBySlug(ctx, tenantID, in.PostingSlug)
	if err != nil {
		return nil, fmt.Errorf("posting not found or not open")
	}

	// Get-or-create candidate by (tenant, email).
	cand, err := s.orm.Candidate.Query().
		Where(candidate.TenantID(tenantID), candidate.Email(in.Email)).First(ctx)
	if ent.IsNotFound(err) {
		c := s.orm.Candidate.Create().
			SetTenantID(tenantID).SetFullName(in.FullName).SetEmail(in.Email)
		if in.Phone != "" {
			c = c.SetPhone(in.Phone)
		}
		if in.ResumeURL != "" {
			c = c.SetResumeURL(in.ResumeURL)
		}
		cand, err = c.Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("candidate: %w", err)
	}

	// Dedup: one application per (posting, candidate).
	if existing, e := s.orm.Application.Query().
		Where(application.TenantID(tenantID), application.JobID(post.ID), application.CandidateID(cand.ID)).
		First(ctx); e == nil {
		return existing, nil
	}

	b := s.orm.Application.Create().
		SetTenantID(tenantID).SetJobID(post.ID).SetCandidateID(cand.ID).
		SetStatus(application.StatusApplied).SetSource("careers_portal")
	if in.CoverLetter != "" {
		b = b.SetCoverLetter(in.CoverLetter)
	}
	app, err := b.Save(ctx)
	if err != nil {
		return nil, err
	}
	// Confirm receipt to the applicant (best-effort).
	s.emailCandidate(ctx, tenantID, app.ID.String(), cand.Email,
		"Application received: "+post.Title,
		"Hi "+cand.FullName+",\n\nThank you for applying for the "+post.Title+" position. "+
			"We have received your application and will be in touch if your profile matches our needs.\n\nBest regards,\nRecruitment Team")
	return app, nil
}
