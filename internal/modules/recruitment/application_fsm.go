package recruitment

import (
	"context"
	"fmt"

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
// On hire it optionally creates an Employee (from the candidate) and seeds onboarding.
// candidateName/email are read from the candidate to populate the new employee row.
func (s *Service) Transition(ctx context.Context, tenantID, id uuid.UUID, to string, createEmployee bool) (TransitionResult, error) {
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
		updated, uerr := app.Update().SetStatus(target).Save(ctx)
		if uerr != nil {
			return res, fmt.Errorf("recruitment: transition: %w", uerr)
		}
		res.Application = updated
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
	emp, err := tx.Employee.Create().
		SetTenantID(tenantID).
		SetFirstName(cand.FullName).
		SetEmail(cand.Email).
		Save(ctx)
	if err != nil {
		return res, fmt.Errorf("recruitment: create employee on hire: %w", err)
	}
	onb, err := seedOnboardingTx(ctx, tx, tenantID, emp.ID)
	if err != nil {
		return res, err
	}
	updated, err := app.Update().SetStatus(target).SetHiredEmployeeID(emp.ID).Save(ctx)
	if err != nil {
		return res, fmt.Errorf("recruitment: hire transition: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return res, fmt.Errorf("recruitment: commit hire: %w", err)
	}
	res.Application = updated
	res.EmployeeID = &emp.ID
	res.OnboardingID = &onb.ID
	return res, nil
}
