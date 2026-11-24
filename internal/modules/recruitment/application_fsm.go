package recruitment

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/application"
)

// allowedTransitions defines the hiring-pipeline FSM. rejected is reachable from any
// non-terminal stage; hired is terminal (only reachable from offered).
var allowedTransitions = map[application.Status][]application.Status{
	application.StatusApplied:   {application.StatusScreening, application.StatusRejected},
	application.StatusScreening: {application.StatusInterview, application.StatusRejected},
	application.StatusInterview: {application.StatusOffered, application.StatusRejected},
	application.StatusOffered:   {application.StatusHired, application.StatusRejected},
	application.StatusHired:     {},
	application.StatusRejected:  {},
}

// splitFullName splits a candidate's full name into the employee's first name and the rest
// as last name ("Jane Wanjiru Mwangi" gives "Jane", "Wanjiru Mwangi").
func splitFullName(full string) (first, last string) {
	parts := strings.Fields(full)
	if len(parts) == 0 {
		return "", ""
	}
	return parts[0], strings.Join(parts[1:], " ")
}

func canTransition(from, to application.Status) bool {
	for _, t := range allowedTransitions[from] {
		if t == to {
			return true
		}
	}
	return false
}

// TransitionResult carries the updated application and (on hire) the created employee +
// onboarding ids.
type TransitionResult struct {
	Application  *ent.Application
	EmployeeID   *uuid.UUID
	OnboardingID *uuid.UUID
}

// Transition moves an application to the next pipeline stage, rejecting invalid transitions.
// TransitionMeta carries optional stage context recorded at the transition (interview date set
// when moving to interview, offer terms when offered, reason when rejected).
type TransitionMeta struct {
	InterviewDate   *time.Time
	OfferDetails    string
	RejectionReason string
}

// applyMeta sets the stage-context fields appropriate to the target status on an update builder.
func applyMeta(u *ent.ApplicationUpdateOne, target application.Status, m TransitionMeta) *ent.ApplicationUpdateOne {
	switch target {
	case application.StatusInterview:
		if m.InterviewDate != nil {
			u = u.SetInterviewDate(*m.InterviewDate)
		}
	case application.StatusOffered:
		if m.OfferDetails != "" {
			u = u.SetOfferDetails(m.OfferDetails)
		}
	case application.StatusRejected:
		if m.RejectionReason != "" {
			u = u.SetRejectionReason(m.RejectionReason)
		}
	}
	return u
}

// On hire it optionally creates an Employee (from the candidate) and seeds onboarding.
// candidateName/email are read from the candidate to populate the new employee row.
func (s *Service) Transition(ctx context.Context, tenantID, id uuid.UUID, to string, createEmployee bool, meta TransitionMeta) (TransitionResult, error) {
	var res TransitionResult
	target := application.Status(to)

	app, err := s.orm.Application.Query().
		Where(application.TenantID(tenantID), application.ID(id)).Only(ctx)
	if err != nil {
		return res, fmt.Errorf("recruitment: load application: %w", err)
	}
	if !canTransition(app.Status, target) {
		return res, fmt.Errorf("recruitment: invalid transition %s -> %s", app.Status, target)
	}

	if target != application.StatusHired || !createEmployee {
		updated, uerr := applyMeta(app.Update().SetStatus(target), target, meta).Save(ctx)
		if uerr != nil {
			return res, fmt.Errorf("recruitment: transition: %w", uerr)
		}
		res.Application = updated
		s.notifyStatus(ctx, tenantID, app.CandidateID, updated.ID.String(), to)
		return res, nil
	}

	// Hired + create employee: do it atomically (employee + onboarding + checklist + app).
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return res, fmt.Errorf("recruitment: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	cand, err := tx.Candidate.Get(ctx, app.CandidateID)
	if err != nil {
		return res, fmt.Errorf("recruitment: load candidate: %w", err)
	}
	// The offer terms recorded on the earlier transition give the start date.
	emp, err := s.hireEmployee(ctx, tx.Client(), tenantID, app, cand)
	if err != nil {
		return res, err
	}
	onb, err := seedOnboardingTx(ctx, tx, tenantID, emp.ID)
	if err != nil {
		return res, err
	}
	// Through the transaction, so a failed commit leaves the application un-hired too.
	updated, err := tx.Application.UpdateOne(app).SetStatus(target).SetHiredEmployeeID(emp.ID).Save(ctx)
	if err != nil {
		return res, fmt.Errorf("recruitment: hire transition: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return res, fmt.Errorf("recruitment: commit hire: %w", err)
	}
	res.Application = updated
	res.EmployeeID = &emp.ID
	res.OnboardingID = &onb.ID
	s.emailCandidate(ctx, tenantID, updated.ID.String(), cand.Email,
		"Welcome aboard!",
		"Hi "+cand.FullName+",\n\nCongratulations — we're delighted to offer you the role. "+
			"Our HR team will reach out shortly with your onboarding details.\n\nWelcome to the team!")
	return res, nil
}

// notifyStatus emails the candidate a stage update for non-hire transitions (interview/offer/
// rejected). Loads the candidate's email; best-effort.
func (s *Service) notifyStatus(ctx context.Context, tenantID, candidateID uuid.UUID, aggregateID, to string) {
	if s.notify == nil {
		return
	}
	cand, err := s.orm.Candidate.Get(ctx, candidateID)
	if err != nil {
		return
	}
	var subject, body string
	switch to {
	case "interview":
		subject = "Your application is progressing"
		body = "Hi " + cand.FullName + ",\n\nGood news — your application has progressed to the interview stage. " +
			"Our team will contact you to arrange the details.\n\nBest regards,\nRecruitment Team"
	case "offered":
		subject = "An offer is on its way"
		body = "Hi " + cand.FullName + ",\n\nWe'd like to extend an offer for the role. Our HR team will be in touch " +
			"with the details shortly.\n\nBest regards,\nRecruitment Team"
	case "rejected":
		subject = "Update on your application"
		body = "Hi " + cand.FullName + ",\n\nThank you for your interest. After careful consideration we won't be " +
			"progressing your application at this time. We wish you the best in your search.\n\nRecruitment Team"
	default:
		return
	}
	s.emailCandidate(ctx, tenantID, aggregateID, cand.Email, subject, body)
}
