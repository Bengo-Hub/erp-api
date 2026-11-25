// Package tasks implements the ERP-internal job/work-item tracker (legacy task_management):
// tenant-scoped tasks with assignments, status/priority, progress, comments and an audit
// log. This is distinct from projects-service projects/tenders — the ERP owns only this
// internal tracker (data-ownership conformance).
package tasks

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/task"
	"github.com/Bengo-Hub/erp-api/internal/ent/taskcomment"
	"github.com/Bengo-Hub/erp-api/internal/ent/tasklog"
	"github.com/Bengo-Hub/erp-api/internal/platform/tenantref"
)

// Service holds task CRUD + status/comment/log logic. Every query is tenant-scoped.
type Service struct {
	orm *ent.Client
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// ListFilter narrows a task listing.
type ListFilter struct {
	Status     string
	AssigneeID *uuid.UUID
}

// List returns tenant-scoped tasks (optionally filtered by status/assignee).
func (s *Service) List(ctx context.Context, tenantID uuid.UUID, f ListFilter) ([]*ent.Task, error) {
	q := s.orm.Task.Query().Where(task.TenantID(tenantID))
	if f.Status != "" {
		q = q.Where(task.StatusEQ(task.Status(f.Status)))
	}
	if f.AssigneeID != nil {
		q = q.Where(task.AssigneeEmployeeID(*f.AssigneeID))
	}
	return q.Order(ent.Desc(task.FieldCreatedAt)).All(ctx)
}

// Get loads one tenant-scoped task with its comments + logs.
func (s *Service) Get(ctx context.Context, tenantID, id uuid.UUID) (*ent.Task, error) {
	return s.orm.Task.Query().
		Where(task.TenantID(tenantID), task.ID(id)).
		WithComments(func(cq *ent.TaskCommentQuery) { cq.Order(ent.Asc(taskcomment.FieldCreatedAt)) }).
		WithLogs(func(lq *ent.TaskLogQuery) { lq.Order(ent.Desc(tasklog.FieldCreatedAt)) }).
		Only(ctx)
}

// CreateInput is the create payload for a task.
type CreateInput struct {
	Title       string
	Description string
	Status      string
	Priority    string
	AssigneeID  *uuid.UUID
	Category    string
	DueDate     *time.Time
	CreatedBy   *uuid.UUID
}

// Create inserts a tenant-scoped task and writes the create log.
func (s *Service) Create(ctx context.Context, tenantID uuid.UUID, in CreateInput) (*ent.Task, error) {
	if in.Title == "" {
		return nil, fmt.Errorf("tasks: title required")
	}
	if err := tenantref.Employee(ctx, s.orm, tenantID, "assignee", in.AssigneeID); err != nil {
		return nil, err
	}
	b := s.orm.Task.Create().SetTenantID(tenantID).SetTitle(in.Title).SetDescription(in.Description)
	if in.Status != "" {
		b = b.SetStatus(task.Status(in.Status))
	}
	if in.Priority != "" {
		b = b.SetPriority(task.Priority(in.Priority))
	}
	if in.AssigneeID != nil {
		b = b.SetAssigneeEmployeeID(*in.AssigneeID)
	}
	if in.Category != "" {
		b = b.SetCategory(in.Category)
	}
	if in.DueDate != nil {
		b = b.SetDueDate(*in.DueDate)
	}
	if in.CreatedBy != nil {
		b = b.SetCreatedBy(*in.CreatedBy)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("tasks: create: %w", err)
	}
	s.log(ctx, tenantID, row.ID, "created", "task created", in.CreatedBy)
	return row, nil
}

// UpdateInput is the partial-update payload for a task.
type UpdateInput struct {
	Title       *string
	Description *string
	Priority    *string
	AssigneeID  *uuid.UUID
	Category    *string
	DueDate     *time.Time
	ActingUser  *uuid.UUID
}

// Update mutates task attributes (non-status). Returns the updated task.
func (s *Service) Update(ctx context.Context, tenantID, id uuid.UUID, in UpdateInput) (*ent.Task, error) {
	cur, err := s.orm.Task.Query().Where(task.TenantID(tenantID), task.ID(id)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("tasks: not found: %w", err)
	}
	u := cur.Update()
	if in.Title != nil {
		u = u.SetTitle(*in.Title)
	}
	if in.Description != nil {
		u = u.SetDescription(*in.Description)
	}
	if in.Priority != nil {
		u = u.SetPriority(task.Priority(*in.Priority))
	}
	if in.Category != nil {
		u = u.SetCategory(*in.Category)
	}
	if in.DueDate != nil {
		u = u.SetDueDate(*in.DueDate)
	}
	if in.AssigneeID != nil {
		if err := tenantref.Employee(ctx, s.orm, tenantID, "assignee", in.AssigneeID); err != nil {
			return nil, err
		}
		u = u.SetAssigneeEmployeeID(*in.AssigneeID)
		s.log(ctx, tenantID, id, "assigned", "task reassigned", in.ActingUser)
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("tasks: update: %w", err)
	}
	return row, nil
}

// taskTransitions defines the task FSM.
var taskTransitions = map[task.Status][]task.Status{
	task.StatusTodo:       {task.StatusInProgress, task.StatusCancelled},
	task.StatusInProgress: {task.StatusBlocked, task.StatusDone, task.StatusCancelled},
	task.StatusBlocked:    {task.StatusInProgress, task.StatusCancelled},
	task.StatusDone:       {task.StatusInProgress},
	task.StatusCancelled:  {task.StatusTodo},
}

// SetStatus transitions a task (validated FSM), setting completed_at on done.
func (s *Service) SetStatus(ctx context.Context, tenantID, id uuid.UUID, status string, actingUser *uuid.UUID) (*ent.Task, error) {
	cur, err := s.orm.Task.Query().Where(task.TenantID(tenantID), task.ID(id)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("tasks: not found: %w", err)
	}
	target := task.Status(status)
	ok := cur.Status == target
	for _, t := range taskTransitions[cur.Status] {
		if t == target {
			ok = true
			break
		}
	}
	if !ok {
		return nil, fmt.Errorf("tasks: invalid transition %s -> %s", cur.Status, target)
	}
	u := cur.Update().SetStatus(target)
	if target == task.StatusDone {
		u = u.SetCompletedAt(time.Now().UTC()).SetProgress(100)
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("tasks: set status: %w", err)
	}
	s.log(ctx, tenantID, id, "status_changed", "status -> "+status, actingUser)
	return row, nil
}

// SetProgress updates the 0-100 progress percentage.
func (s *Service) SetProgress(ctx context.Context, tenantID, id uuid.UUID, progress int, actingUser *uuid.UUID) (*ent.Task, error) {
	if progress < 0 || progress > 100 {
		return nil, fmt.Errorf("tasks: progress must be 0-100")
	}
	n, err := s.orm.Task.Update().
		Where(task.TenantID(tenantID), task.ID(id)).SetProgress(progress).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("tasks: set progress: %w", err)
	}
	if n == 0 {
		return nil, fmt.Errorf("tasks: not found")
	}
	s.log(ctx, tenantID, id, "progress", fmt.Sprintf("progress -> %d%%", progress), actingUser)
	return s.orm.Task.Query().Where(task.TenantID(tenantID), task.ID(id)).Only(ctx)
}

// Delete removes a task and its comments/logs.
func (s *Service) Delete(ctx context.Context, tenantID, id uuid.UUID) error {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return fmt.Errorf("tasks: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	_, _ = tx.TaskComment.Delete().Where(taskcomment.TenantID(tenantID), taskcomment.TaskID(id)).Exec(ctx)
	_, _ = tx.TaskLog.Delete().Where(tasklog.TenantID(tenantID), tasklog.TaskID(id)).Exec(ctx)
	n, err := tx.Task.Delete().Where(task.TenantID(tenantID), task.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("tasks: delete: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("tasks: not found")
	}
	return tx.Commit()
}

// ---- Comments ----

// AddComment appends a comment to a task and logs it.
func (s *Service) AddComment(ctx context.Context, tenantID, taskID uuid.UUID, body string, author *uuid.UUID) (*ent.TaskComment, error) {
	if body == "" {
		return nil, fmt.Errorf("tasks: comment body required")
	}
	// Ensure the task belongs to the tenant.
	if _, err := s.orm.Task.Query().Where(task.TenantID(tenantID), task.ID(taskID)).Only(ctx); err != nil {
		return nil, fmt.Errorf("tasks: task not found: %w", err)
	}
	b := s.orm.TaskComment.Create().SetTenantID(tenantID).SetTaskID(taskID).SetBody(body)
	if author != nil {
		b = b.SetAuthorUserID(*author)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("tasks: add comment: %w", err)
	}
	s.log(ctx, tenantID, taskID, "comment", "comment added", author)
	return row, nil
}

// log appends a TaskLog audit row (best-effort).
func (s *Service) log(ctx context.Context, tenantID, taskID uuid.UUID, action, desc string, user *uuid.UUID) {
	b := s.orm.TaskLog.Create().
		SetTenantID(tenantID).SetTaskID(taskID).SetAction(action).SetDescription(desc)
	if user != nil {
		b = b.SetUserID(*user)
	}
	_, _ = b.Save(ctx)
}
