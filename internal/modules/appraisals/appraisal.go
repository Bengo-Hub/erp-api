package appraisals

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisal"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalcycle"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalquestion"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalresponse"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisaltemplate"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/predicate"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
	"github.com/Bengo-Hub/erp-api/internal/platform/tenantref"
)

// ListAppraisals returns appraisals filtered by tenant (+ optional cycle/employee). A search
// term keeps the appraisals whose employee's name or staff number contains every word of it.
func (s *Service) ListAppraisals(ctx context.Context, tenantID uuid.UUID, cycleID, employeeID *uuid.UUID, search string) ([]*ent.Appraisal, error) {
	q := s.orm.Appraisal.Query().Where(appraisal.TenantID(tenantID))
	if cycleID != nil {
		q = q.Where(appraisal.CycleID(*cycleID))
	}
	if employeeID != nil {
		q = q.Where(appraisal.EmployeeID(*employeeID))
	}
	if words := searchWords(search); len(words) > 0 {
		q = q.Where(employeeMatches(tenantID, words))
	}
	return q.Order(ent.Desc(appraisal.FieldCreatedAt)).All(ctx)
}

// Search bounds: longer input is cut, extra words are ignored.
const (
	maxSearchLen   = 100
	maxSearchWords = 4
)

// searchWords splits a search term into at most maxSearchWords words.
func searchWords(search string) []string {
	search = strings.TrimSpace(search)
	if len(search) > maxSearchLen {
		search = search[:maxSearchLen]
	}
	words := strings.Fields(search)
	if len(words) > maxSearchWords {
		words = words[:maxSearchWords]
	}
	return words
}

// employeeMatches keeps appraisals whose employee (same tenant) has every word in the first
// name, last name or staff number, case-insensitively (ILIKE on Postgres), as one
// "employee_id IN (SELECT ...)" subquery.
func employeeMatches(tenantID uuid.UUID, words []string) predicate.Appraisal {
	return func(s *entsql.Selector) {
		t := entsql.Table(employee.Table)
		sub := entsql.Select(t.C(employee.FieldID)).From(t)
		employee.TenantID(tenantID)(sub)
		for _, w := range words {
			employee.Or(
				employee.FirstNameContainsFold(w),
				employee.LastNameContainsFold(w),
				employee.EmployeeNumberContainsFold(w),
			)(sub)
		}
		s.Where(entsql.In(s.C(appraisal.FieldEmployeeID), sub))
	}
}

// AppraisalView is an appraisal with the employee, evaluator, cycle and template names a
// screen shows next to it.
type AppraisalView struct {
	*ent.Appraisal
	EmployeeName   string `json:"employee_name,omitempty"`
	EmployeeNumber string `json:"employee_number,omitempty"`
	EvaluatorName  string `json:"evaluator_name,omitempty"`
	CycleName      string `json:"cycle_name,omitempty"`
	TemplateName   string `json:"template_name,omitempty"`
}

// tenantScope is the tenant plus the system tenant whose standard templates every tenant
// inherits (see ListTemplates).
func (s *Service) tenantScope(tenantID uuid.UUID) []uuid.UUID {
	if s.systemTenant == uuid.Nil || s.systemTenant == tenantID {
		return []uuid.UUID{tenantID}
	}
	return []uuid.UUID{tenantID, s.systemTenant}
}

// DescribeAppraisals adds the employee, evaluator, cycle and template names to appraisals,
// loading each kind in one query.
func (s *Service) DescribeAppraisals(ctx context.Context, tenantID uuid.UUID, rows []*ent.Appraisal) ([]AppraisalView, error) {
	out := make([]AppraisalView, len(rows))
	if len(rows) == 0 {
		return out, nil
	}
	var empIDs, cycleIDs, templateIDs []uuid.UUID
	for _, a := range rows {
		empIDs = append(empIDs, a.EmployeeID)
		if a.EvaluatorID != nil {
			empIDs = append(empIDs, *a.EvaluatorID)
		}
		cycleIDs = append(cycleIDs, a.CycleID)
		if a.TemplateID != nil {
			templateIDs = append(templateIDs, *a.TemplateID)
		}
	}
	emps, err := s.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.IDIn(empIDs...)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: load employees: %w", err)
	}
	names := make(map[uuid.UUID]*ent.Employee, len(emps))
	for _, e := range emps {
		names[e.ID] = e
	}
	cycles, err := s.orm.AppraisalCycle.Query().
		Where(appraisalcycle.TenantID(tenantID), appraisalcycle.IDIn(cycleIDs...)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: load cycles: %w", err)
	}
	cycleNames := make(map[uuid.UUID]string, len(cycles))
	for _, c := range cycles {
		cycleNames[c.ID] = c.Name
	}
	templateNames := map[uuid.UUID]string{}
	if len(templateIDs) > 0 {
		tpls, terr := s.orm.AppraisalTemplate.Query().
			Where(appraisaltemplate.TenantIDIn(s.tenantScope(tenantID)...), appraisaltemplate.IDIn(templateIDs...)).All(ctx)
		if terr != nil {
			return nil, fmt.Errorf("appraisals: load templates: %w", terr)
		}
		for _, t := range tpls {
			templateNames[t.ID] = t.Name
		}
	}
	for i, a := range rows {
		v := AppraisalView{Appraisal: a, CycleName: cycleNames[a.CycleID]}
		if a.TemplateID != nil {
			v.TemplateName = templateNames[*a.TemplateID]
		}
		if e := names[a.EmployeeID]; e != nil {
			v.EmployeeName = fullName(e)
			if e.EmployeeNumber != nil {
				v.EmployeeNumber = *e.EmployeeNumber
			}
		}
		if a.EvaluatorID != nil {
			if e := names[*a.EvaluatorID]; e != nil {
				v.EvaluatorName = fullName(e)
			}
		}
		out[i] = v
	}
	return out, nil
}

func fullName(e *ent.Employee) string {
	return strings.TrimSpace(e.FirstName + " " + e.LastName)
}

// GetAppraisal returns one tenant-scoped appraisal with its names.
func (s *Service) GetAppraisal(ctx context.Context, tenantID, id uuid.UUID) (*AppraisalView, error) {
	a, err := s.orm.Appraisal.Query().Where(appraisal.TenantID(tenantID), appraisal.ID(id)).Only(ctx)
	if err != nil {
		return nil, err
	}
	views, err := s.DescribeAppraisals(ctx, tenantID, []*ent.Appraisal{a})
	if err != nil {
		return nil, err
	}
	return &views[0], nil
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
	if err := tenantref.Require(ctx, "appraisal cycle", s.orm.AppraisalCycle.Query().
		Where(appraisalcycle.TenantID(tenantID), appraisalcycle.ID(in.CycleID))); err != nil {
		return nil, err
	}
	if err := tenantref.Employee(ctx, s.orm, tenantID, "employee", &in.EmployeeID); err != nil {
		return nil, err
	}
	if err := tenantref.Employee(ctx, s.orm, tenantID, "evaluator", in.EvaluatorID); err != nil {
		return nil, err
	}
	if in.TemplateID != nil { // the tenant's own or the shared standard template
		if err := tenantref.Require(ctx, "appraisal template", s.orm.AppraisalTemplate.Query().
			Where(appraisaltemplate.TenantIDIn(s.tenantScope(tenantID)...), appraisaltemplate.ID(*in.TemplateID))); err != nil {
			return nil, err
		}
	}
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

	// Sprint 4: route the completed->approved/rejected review through the approvals engine
	// when the tenant has an open appraisal approval workflow. Intermediate steps keep the
	// appraisal in `completed` until the chain finishes.
	if a.Status == appraisal.StatusCompleted && (target == appraisal.StatusApproved || target == appraisal.StatusRejected) {
		proceed, out, rerr := s.routeAppraisalDecision(ctx, tenantID, id, target == appraisal.StatusApproved, rejectionReason)
		if rerr != nil {
			return nil, rerr
		}
		if !proceed {
			return out, nil
		}
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

	// On completion, open an approval request so the configured chain can review it.
	if target == appraisal.StatusCompleted && s.approvals != nil {
		empID := row.EmployeeID
		_, _ = s.approvals.Submit(ctx, tenantID, approvals.SubmitInput{
			Module:              moduleAppraisal,
			ObjectID:            row.ID,
			ObjectReference:     "appraisal:" + row.ID.String(),
			RequesterEmployeeID: &empID,
			SubmittedBy:         row.EvaluatorID,
		})
	}
	return row, nil
}

// routeAppraisalDecision drives the approvals engine for an appraisal review. Returns
// proceed=true when the caller should apply the FSM transition itself (no engine wired, no
// open request, or the chain just reached a terminal state); proceed=false (with the
// unchanged appraisal) when only an intermediate step was recorded.
func (s *Service) routeAppraisalDecision(ctx context.Context, tenantID, id uuid.UUID, approve bool, comment string) (bool, *ent.Appraisal, error) {
	if s.approvals == nil {
		return true, nil, nil
	}
	apr, err := s.approvals.FindRequestForObject(ctx, tenantID, moduleAppraisal, id)
	if ent.IsNotFound(err) {
		return true, nil, nil
	}
	if err != nil {
		return false, nil, fmt.Errorf("appraisals: find approval request: %w", err)
	}
	if apr.Status != "pending" {
		return true, nil, nil
	}
	dec, err := s.approvals.Decide(ctx, tenantID, approvals.DecisionInput{
		RequestID: apr.ID, Approve: approve, Comment: comment,
	})
	if err != nil {
		return false, nil, fmt.Errorf("appraisals: approval decision: %w", err)
	}
	if approve && !dec.Finished {
		cur, gerr := s.orm.Appraisal.Query().Where(appraisal.TenantID(tenantID), appraisal.ID(id)).Only(ctx)
		return false, cur, gerr
	}
	return true, nil, nil
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

// ErrAppraisalLocked is returned when answers are saved on an appraisal that is no longer
// being evaluated (completed, approved or rejected); a rejected one is reopened first.
var ErrAppraisalLocked = errors.New("appraisals: this appraisal is not open for evaluation")

// AddResponse records the answer to a question within an appraisal. Saving the same
// question again replaces the earlier answer, and the first answer on a draft appraisal
// moves it to in_progress.
func (s *Service) AddResponse(ctx context.Context, tenantID uuid.UUID, in ResponseInput) (*ent.AppraisalResponse, error) {
	rating, rerr := parseRating(in.Rating)
	if rerr != nil {
		return nil, fmt.Errorf("appraisals: %w", rerr)
	}
	a, err := s.orm.Appraisal.Query().
		Where(appraisal.TenantID(tenantID), appraisal.ID(in.AppraisalID)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: load appraisal: %w", err)
	}
	if a.Status != appraisal.StatusDraft && a.Status != appraisal.StatusInProgress {
		return nil, ErrAppraisalLocked
	}
	if ok, qerr := s.orm.AppraisalQuestion.Query().
		Where(appraisalquestion.TenantIDIn(s.tenantScope(tenantID)...), appraisalquestion.ID(in.QuestionID)).
		Exist(ctx); qerr != nil {
		return nil, fmt.Errorf("appraisals: load question: %w", qerr)
	} else if !ok {
		return nil, fmt.Errorf("appraisals: question not found")
	}

	existing, err := s.orm.AppraisalResponse.Query().
		Where(appraisalresponse.TenantID(tenantID), appraisalresponse.AppraisalID(in.AppraisalID),
			appraisalresponse.QuestionID(in.QuestionID)).
		First(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return nil, fmt.Errorf("appraisals: load response: %w", err)
	}
	var row *ent.AppraisalResponse
	if existing != nil {
		u := existing.Update().SetResponse(in.Response)
		if rating != nil {
			u = u.SetRating(*rating)
		} else {
			u = u.ClearRating()
		}
		row, err = u.Save(ctx)
	} else {
		b := s.orm.AppraisalResponse.Create().
			SetTenantID(tenantID).SetAppraisalID(in.AppraisalID).SetQuestionID(in.QuestionID).
			SetResponse(in.Response)
		if rating != nil {
			b = b.SetRating(*rating)
		}
		row, err = b.Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("appraisals: save response: %w", err)
	}
	if a.Status == appraisal.StatusDraft {
		if _, uerr := a.Update().SetStatus(appraisal.StatusInProgress).Save(ctx); uerr != nil {
			return nil, fmt.Errorf("appraisals: start appraisal: %w", uerr)
		}
	}
	return row, nil
}
