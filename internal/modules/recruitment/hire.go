package recruitment

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/department"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobposting"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobtitle"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
)

// WithStaffNumbers wires the staff-number generator the employees service uses, so an
// employee created on hire gets a staff number like one created on the employees screen.
func (s *Service) WithStaffNumbers(seq employees.StaffNumberer) *Service {
	s.staffNumbers = seq
	return s
}

// startDatePattern finds a start date written into the offer terms as "Start date:
// 2026-12-01" (also "Starting 2026-12-01" or "Start 2026-12-01").
var startDatePattern = regexp.MustCompile(`(?i)\bstart(?:ing)?(?:\s+date)?\s*[:=-]?\s*(\d{4}-\d{2}-\d{2})\b`)

// offerStartDate returns the start date stated in the offer terms, or nil when none is.
func offerStartDate(offer *string) *time.Time {
	if offer == nil {
		return nil
	}
	m := startDatePattern.FindStringSubmatch(*offer)
	if m == nil {
		return nil
	}
	d, err := time.Parse("2006-01-02", m[1])
	if err != nil {
		return nil
	}
	return &d
}

// hireHR builds the employment details a hire can take from the job posting and the offer:
// the department and job title whose names match the posting (the tenant's own, or a shared
// platform department) and the offered start date. Anything that does not match is left
// out; nothing is created.
func hireHR(ctx context.Context, c *ent.Client, tenantID uuid.UUID, app *ent.Application) (employees.HRInput, error) {
	var in employees.HRInput
	in.DateJoined = offerStartDate(app.OfferDetails)
	posting, err := c.JobPosting.Query().
		Where(jobposting.TenantID(tenantID), jobposting.ID(app.JobID)).Only(ctx)
	if ent.IsNotFound(err) {
		return in, nil
	}
	if err != nil {
		return in, fmt.Errorf("recruitment: load job posting: %w", err)
	}
	if posting.Department != nil {
		if name := strings.TrimSpace(*posting.Department); name != "" {
			// The tenant's own department wins over a shared one of the same name.
			deps, derr := c.Department.Query().Where(department.TitleEqualFold(name),
				department.Or(department.TenantID(tenantID), department.TenantIDIsNil())).All(ctx)
			if derr != nil {
				return in, fmt.Errorf("recruitment: match department: %w", derr)
			}
			for _, d := range deps {
				id := d.ID
				if in.DepartmentID == nil || (d.TenantID != nil && *d.TenantID == tenantID) {
					in.DepartmentID = &id
				}
			}
		}
	}
	if title := strings.TrimSpace(posting.Title); title != "" {
		jt, jerr := c.JobTitle.Query().
			Where(jobtitle.TenantID(tenantID), jobtitle.TitleEqualFold(title)).First(ctx)
		if jerr != nil && !ent.IsNotFound(jerr) {
			return in, fmt.Errorf("recruitment: match job title: %w", jerr)
		}
		if jt != nil {
			id := jt.ID
			in.JobTitleID = &id
		}
	}
	return in, nil
}

// hireEmployee creates the employee for a hired candidate through the employees service on
// the given (transaction) client: name and email, the candidate's phone, and the department,
// job title and start date hireHR finds.
func (s *Service) hireEmployee(ctx context.Context, c *ent.Client, tenantID uuid.UUID, app *ent.Application, cand *ent.Candidate) (*ent.Employee, error) {
	first, last := splitFullName(cand.FullName)
	if last == "" {
		return nil, fmt.Errorf("recruitment: the candidate needs a first and last name before an employee record can be created; edit the candidate's full name")
	}
	svc := employees.NewService(c)
	if s.staffNumbers != nil {
		svc = svc.WithSequence(s.staffNumbers)
	}
	emp, err := svc.Create(ctx, tenantID, employees.CreateInput{FirstName: first, LastName: last, Email: cand.Email})
	if err != nil {
		return nil, fmt.Errorf("recruitment: create employee on hire: %w", err)
	}
	if cand.Phone != nil {
		if err := svc.SetPhone(ctx, tenantID, emp.ID, *cand.Phone); err != nil {
			return nil, fmt.Errorf("recruitment: copy phone on hire: %w", err)
		}
	}
	hr, err := hireHR(ctx, c, tenantID, app)
	if err != nil {
		return nil, err
	}
	if err := svc.UpsertHR(ctx, tenantID, emp.ID, hr); err != nil {
		return nil, fmt.Errorf("recruitment: employment details on hire: %w", err)
	}
	return emp, nil
}
