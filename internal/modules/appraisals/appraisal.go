package appraisals

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisal"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalresponse"
)

// ListAppraisals returns appraisals filtered by tenant (+ optional cycle/employee).
func (s *Service) ListAppraisals(ctx context.Context, tenantID uuid.UUID, cycleID, employeeID *uuid.UUID) ([]*ent.Appraisal, error) {
	q := s.orm.Appraisal.Query().Where(appraisal.TenantID(tenantID))
	if cycleID != nil {
		q = q.Where(appraisal.CycleID(*cycleID))
	}
	if employeeID != nil {
		q = q.Where(appraisal.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(appraisal.FieldCreatedAt)).All(ctx)
}

// AppraisalInput is the create payload for an appraisal.
type AppraisalInput struct {
	CycleID     uuid.UUID
	EmployeeID  uuid.UUID
	EvaluatorID *uuid.UUID
	TemplateID  *uuid.UUID
}

// CreateAppraisal opens a draft appraisal for an employee within a cycle.
func (s *Service) CreateAppraisal(ctx context.Context, tenantID uuid.UUID, in AppraisalInput) (*ent.Appraisal, error) {
	b := s.orm.Appraisal.Create().
		SetTenantID(tenantID).SetCycleID(in.CycleID).SetEmployeeID(in.EmployeeID).
		SetStatus(appraisal.StatusDraft)
	if in.EvaluatorID != nil {
		b = b.SetEvaluatorID(*in.EvaluatorID)
	}
	if in.TemplateID != nil {
		b = b.SetTemplateID(*in.TemplateID)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: create appraisal: %w", err)
	}
	return row, nil
}

// appraisalTransitions defines the appraisal FSM. rejected is reachable from completed
// (review rejection); approved from completed.
var appraisalTransitions = map[appraisal.Status][]appraisal.Status{
	appraisal.StatusDraft:      {appraisal.StatusInProgress},
	appraisal.StatusInProgress: {appraisal.StatusCompleted},
	appraisal.StatusCompleted:  {appraisal.StatusApproved, appraisal.StatusRejected},
	appraisal.StatusApproved:   {},
	appraisal.StatusRejected:   {appraisal.StatusInProgress},
}

// SetAppraisalStatus transitions an appraisal, rejecting invalid transitions. overallRating
// (0-5, optional) and rejectionReason are applied where relevant.
func (s *Service) SetAppraisalStatus(ctx context.Context, tenantID, id uuid.UUID, status, overallRating, rejectionReason string) (*ent.Appraisal, error) {
	a, err := s.orm.Appraisal.Query().Where(appraisal.TenantID(tenantID), appraisal.ID(id)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: load appraisal: %w", err)
	}
	target := appraisal.Status(status)
	ok := false
	for _, t := range appraisalTransitions[a.Status] {
		if t == target {
			ok = true
			break
		}
	}
	if !ok {
		return nil, fmt.Errorf("appraisals: invalid appraisal transition %s -> %s", a.Status, target)
	}
	u := a.Update().SetStatus(target)
	if rating, rerr := parseRating(overallRating); rerr != nil {
		return nil, fmt.Errorf("appraisals: %w", rerr)
	} else if rating != nil {
		u = u.SetOverallRating(*rating)
	}
	switch target {
	case appraisal.StatusApproved:
		u = u.SetApprovedAt(time.Now().UTC())
	case appraisal.StatusRejected:
		u = u.SetRejectedAt(time.Now().UTC()).SetRejectionReason(rejectionReason)
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: transition: %w", err)
	}
	return row, nil
}

// ---- Responses ----

// ListResponses returns the responses for a tenant-scoped appraisal.
func (s *Service) ListResponses(ctx context.Context, tenantID, appraisalID uuid.UUID) ([]*ent.AppraisalResponse, error) {
	return s.orm.AppraisalResponse.Query().
		Where(appraisalresponse.TenantID(tenantID), appraisalresponse.AppraisalID(appraisalID)).All(ctx)
}

// ResponseInput is the create payload for an appraisal response.
type ResponseInput struct {
	AppraisalID uuid.UUID
	QuestionID  uuid.UUID
	Response    string
	Rating      string
}

// AddResponse records an answer to a question within an appraisal.
func (s *Service) AddResponse(ctx context.Context, tenantID uuid.UUID, in ResponseInput) (*ent.AppraisalResponse, error) {
	b := s.orm.AppraisalResponse.Create().
		SetTenantID(tenantID).SetAppraisalID(in.AppraisalID).SetQuestionID(in.QuestionID).
		SetResponse(in.Response)
	if rating, rerr := parseRating(in.Rating); rerr != nil {
		return nil, fmt.Errorf("appraisals: %w", rerr)
	} else if rating != nil {
		b = b.SetRating(*rating)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: add response: %w", err)
	}
	return row, nil
}
