package appraisals

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/goal"
	"github.com/Bengo-Hub/erp-api/internal/ent/goalprogress"
)

// ListGoals returns goals filtered by tenant (+ optional employee; templates included).
func (s *Service) ListGoals(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.Goal, error) {
	q := s.orm.Goal.Query().Where(goal.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(goal.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(goal.FieldCreatedAt)).All(ctx)
}

// GoalView is a goal with its employee's name and its metadata fields (category, weight)
// at the top level.
type GoalView struct {
	*ent.Goal
	EmployeeName string `json:"employee_name,omitempty"`
	Category     string `json:"category,omitempty"`
	Weight       string `json:"weight,omitempty"`
}

// DescribeGoals adds employee names (one query) and flattens category and weight.
func (s *Service) DescribeGoals(ctx context.Context, tenantID uuid.UUID, rows []*ent.Goal) ([]GoalView, error) {
	var ids []uuid.UUID
	for _, g := range rows {
		if g.EmployeeID != nil {
			ids = append(ids, *g.EmployeeID)
		}
	}
	names := map[uuid.UUID]string{}
	if len(ids) > 0 {
		emps, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(ids...)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("appraisals: load employees: %w", err)
		}
		for _, e := range emps {
			names[e.ID] = fullName(e)
		}
	}
	out := make([]GoalView, len(rows))
	for i, g := range rows {
		v := GoalView{Goal: g}
		if g.EmployeeID != nil {
			v.EmployeeName = names[*g.EmployeeID]
		}
		if c, ok := g.Metadata["category"].(string); ok {
			v.Category = c
		}
		if w, ok := g.Metadata["weight"]; ok && w != nil {
			v.Weight = fmt.Sprint(w)
		}
		out[i] = v
	}
	return out, nil
}

// GoalInput is the create payload for an employee goal. EmployeeID is nil for a library
// template. Category and Weight have no columns; they are kept in the goal metadata.
type GoalInput struct {
	EmployeeID  *uuid.UUID
	Title       string
	Description string
	StartDate   *time.Time
	EndDate     *time.Time
	IsTemplate  bool
	CreatedBy   *uuid.UUID
	Category    string
	Weight      string
}

// CreateGoal inserts a tenant-scoped goal (status not_started, progress 0).
func (s *Service) CreateGoal(ctx context.Context, tenantID uuid.UUID, in GoalInput) (*ent.Goal, error) {
	md := map[string]any{}
	if c := strings.TrimSpace(in.Category); c != "" {
		md["category"] = c
	}
	if in.Weight != "" {
		w, err := decimal.NewFromString(in.Weight)
		if err != nil || w.IsNegative() {
			return nil, fmt.Errorf("appraisals: weight must be a number of zero or more")
		}
		md["weight"] = w.String()
	}
	b := s.orm.Goal.Create().
		SetTenantID(tenantID).SetNillableEmployeeID(in.EmployeeID).
		SetTitle(in.Title).SetDescription(in.Description).
		SetStatus(goal.StatusNotStarted).SetProgress(0).SetIsTemplate(in.IsTemplate).
		SetMetadata(md)
	if in.StartDate != nil {
		b = b.SetStartDate(*in.StartDate)
	}
	if in.EndDate != nil {
		b = b.SetEndDate(*in.EndDate)
	}
	if in.CreatedBy != nil {
		b = b.SetCreatedBy(*in.CreatedBy)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: create goal: %w", err)
	}
	return row, nil
}

// AddProgress records a progress update (0-100) and syncs the goal's progress/status
// (>=100 -> completed; >0 -> in_progress).
func (s *Service) AddProgress(ctx context.Context, tenantID, goalID uuid.UUID, progress int, comments string, updatedBy *uuid.UUID) (*ent.GoalProgress, error) {
	if progress < 0 || progress > 100 {
		return nil, fmt.Errorf("appraisals: progress must be 0-100")
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	g, err := tx.Goal.Query().Where(goal.TenantID(tenantID), goal.ID(goalID)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: load goal: %w", err)
	}
	pb := tx.GoalProgress.Create().
		SetTenantID(tenantID).SetGoalID(goalID).SetProgress(progress).SetComments(comments)
	if updatedBy != nil {
		pb = pb.SetUpdatedBy(*updatedBy)
	}
	row, err := pb.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: add progress: %w", err)
	}

	status := goal.StatusInProgress
	if progress >= 100 {
		status = goal.StatusCompleted
	} else if progress == 0 {
		status = goal.StatusNotStarted
	}
	if _, err := g.Update().SetProgress(progress).SetStatus(status).Save(ctx); err != nil {
		return nil, fmt.Errorf("appraisals: sync goal progress: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("appraisals: commit progress: %w", err)
	}
	return row, nil
}

// ListProgress returns the progress updates for a tenant-scoped goal.
func (s *Service) ListProgress(ctx context.Context, tenantID, goalID uuid.UUID) ([]*ent.GoalProgress, error) {
	return s.orm.GoalProgress.Query().
		Where(goalprogress.TenantID(tenantID), goalprogress.GoalID(goalID)).
		Order(ent.Desc(goalprogress.FieldCreatedAt)).All(ctx)
}
