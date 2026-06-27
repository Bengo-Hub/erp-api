// Package appraisals implements tenant-isolated appraisals: cycles, templates/questions,
// appraisals (FSM) with responses, and employee goals with progress updates.
package appraisals

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalcycle"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalquestion"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisaltemplate"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
)

// moduleAppraisal is the approvals-engine module key for appraisal reviews.
const moduleAppraisal = "appraisal"

// Approver is the slice of the approvals engine the appraisals module needs. When a tenant
// has configured an appraisal approval workflow, the completed->approved review routes
// through it (Sprint 4); otherwise the FSM transition applies directly.
type Approver interface {
	Submit(ctx context.Context, tenantID uuid.UUID, in approvals.SubmitInput) (*ent.ApprovalRequest, error)
	FindRequestForObject(ctx context.Context, tenantID uuid.UUID, module string, objectID uuid.UUID) (*ent.ApprovalRequest, error)
	Decide(ctx context.Context, tenantID uuid.UUID, in approvals.DecisionInput) (*approvals.Decision, error)
}

// Service holds appraisal/goal CRUD + FSMs. Tenant-scoped.
type Service struct {
	orm       *ent.Client
	approvals Approver
	// systemTenant owns the GLOBAL shared appraisal templates; a tenant with none of its own
	// inherits them (feedback_shared_core_reference_data). uuid.Nil = no fallback.
	systemTenant uuid.UUID
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// SetApprovals wires the approval engine into the appraisals module (called at startup).
func (s *Service) SetApprovals(a Approver) { s.approvals = a }

// WithSystemTenant sets the global-templates fallback tenant (chainable, startup wiring).
func (s *Service) WithSystemTenant(id uuid.UUID) *Service { s.systemTenant = id; return s }

// ---- Cycles ----

// ListCycles returns tenant-scoped appraisal cycles.
func (s *Service) ListCycles(ctx context.Context, tenantID uuid.UUID) ([]*ent.AppraisalCycle, error) {
	return s.orm.AppraisalCycle.Query().
		Where(appraisalcycle.TenantID(tenantID)).
		Order(ent.Desc(appraisalcycle.FieldCreatedAt)).All(ctx)
}

// CycleInput is the create payload for an appraisal cycle.
type CycleInput struct {
	Name        string
	Description string
	StartDate   time.Time
	EndDate     time.Time
	DueDate     *time.Time
	CreatedBy   *uuid.UUID
}

// CreateCycle inserts a tenant-scoped appraisal cycle (status created).
func (s *Service) CreateCycle(ctx context.Context, tenantID uuid.UUID, in CycleInput) (*ent.AppraisalCycle, error) {
	b := s.orm.AppraisalCycle.Create().
		SetTenantID(tenantID).SetName(in.Name).SetDescription(in.Description).
		SetStartDate(in.StartDate).SetEndDate(in.EndDate).SetStatus(appraisalcycle.StatusCreated)
	if in.DueDate != nil {
		b = b.SetDueDate(*in.DueDate)
	}
	if in.CreatedBy != nil {
		b = b.SetCreatedBy(*in.CreatedBy)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: create cycle: %w", err)
	}
	return row, nil
}

// cycleTransitions defines the cycle FSM.
var cycleTransitions = map[appraisalcycle.Status][]appraisalcycle.Status{
	appraisalcycle.StatusCreated:   {appraisalcycle.StatusActivated},
	appraisalcycle.StatusActivated: {appraisalcycle.StatusClosed},
	appraisalcycle.StatusClosed:    {appraisalcycle.StatusReopened},
	appraisalcycle.StatusReopened:  {appraisalcycle.StatusClosed},
}

// SetCycleStatus transitions a cycle, rejecting invalid transitions.
func (s *Service) SetCycleStatus(ctx context.Context, tenantID, id uuid.UUID, status string) (*ent.AppraisalCycle, error) {
	c, err := s.orm.AppraisalCycle.Query().
		Where(appraisalcycle.TenantID(tenantID), appraisalcycle.ID(id)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: load cycle: %w", err)
	}
	target := appraisalcycle.Status(status)
	ok := false
	for _, t := range cycleTransitions[c.Status] {
		if t == target {
			ok = true
			break
		}
	}
	if !ok {
		return nil, fmt.Errorf("appraisals: invalid cycle transition %s -> %s", c.Status, target)
	}
	return c.Update().SetStatus(target).Save(ctx)
}

// ---- Templates + questions ----

// ListTemplates returns tenant-scoped appraisal templates.
func (s *Service) ListTemplates(ctx context.Context, tenantID uuid.UUID) ([]*ent.AppraisalTemplate, error) {
	own, err := s.orm.AppraisalTemplate.Query().
		Where(appraisaltemplate.TenantID(tenantID)).
		Order(ent.Desc(appraisaltemplate.FieldCreatedAt)).All(ctx)
	if err != nil {
		return nil, err
	}
	if len(own) > 0 || s.systemTenant == uuid.Nil || s.systemTenant == tenantID {
		return own, nil
	}
	// Inherit the global standard appraisal template when the tenant has none of its own.
	return s.orm.AppraisalTemplate.Query().
		Where(appraisaltemplate.TenantID(s.systemTenant)).
		Order(ent.Desc(appraisaltemplate.FieldCreatedAt)).All(ctx)
}

// CreateTemplate inserts a tenant-scoped template.
func (s *Service) CreateTemplate(ctx context.Context, tenantID uuid.UUID, name, description string, createdBy *uuid.UUID) (*ent.AppraisalTemplate, error) {
	b := s.orm.AppraisalTemplate.Create().
		SetTenantID(tenantID).SetName(name).SetDescription(description).SetIsActive(true)
	if createdBy != nil {
		b = b.SetCreatedBy(*createdBy)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: create template: %w", err)
	}
	return row, nil
}

// ListQuestions returns the questions for a tenant-scoped template.
func (s *Service) ListQuestions(ctx context.Context, tenantID, templateID uuid.UUID) ([]*ent.AppraisalQuestion, error) {
	return s.orm.AppraisalQuestion.Query().
		Where(appraisalquestion.TenantID(tenantID), appraisalquestion.TemplateID(templateID)).
		Order(ent.Asc(appraisalquestion.FieldOrder)).All(ctx)
}

// QuestionInput is the create payload for a template question.
type QuestionInput struct {
	TemplateID   uuid.UUID
	QuestionText string
	QuestionType string
	IsRequired   bool
	Order        int
	Category     string
	Weight       *float64
	MaxScore     *int
}

// AddQuestion appends a question to a template.
func (s *Service) AddQuestion(ctx context.Context, tenantID uuid.UUID, in QuestionInput) (*ent.AppraisalQuestion, error) {
	c := s.orm.AppraisalQuestion.Create().
		SetTenantID(tenantID).SetTemplateID(in.TemplateID).
		SetQuestionText(in.QuestionText).
		SetQuestionType(appraisalquestion.QuestionType(in.QuestionType)).
		SetIsRequired(in.IsRequired).SetOrder(in.Order)
	if in.Category != "" {
		c.SetCategory(in.Category)
	}
	if in.Weight != nil {
		c.SetWeight(*in.Weight)
	}
	if in.MaxScore != nil {
		c.SetMaxScore(*in.MaxScore)
	}
	row, err := c.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: add question: %w", err)
	}
	return row, nil
}

// parseRating parses an optional 0-5 rating string; empty -> nil.
func parseRating(s string) (*decimal.Decimal, error) {
	if s == "" {
		return nil, nil
	}
	d, err := decimal.NewFromString(s)
	if err != nil {
		return nil, err
	}
	if d.LessThan(decimal.Zero) || d.GreaterThan(decimal.NewFromInt(5)) {
		return nil, fmt.Errorf("rating must be between 0 and 5")
	}
	return &d, nil
}
