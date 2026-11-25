package recruitment

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeonboarding"
	"github.com/Bengo-Hub/erp-api/internal/ent/onboardingtask"
	"github.com/Bengo-Hub/erp-api/internal/platform/tenantref"
)

// defaultOnboardingTasks is the checklist seeded when onboarding starts (port of
// recruitment.onboarding_models.DEFAULT_ONBOARDING_TASKS).
var defaultOnboardingTasks = []struct {
	Category string
	Title    string
}{
	{"IT", "Provision laptop / equipment"},
	{"IT", "Create email & system accounts"},
	{"IT", "Grant building / door access"},
	{"HR", "Collect signed contract"},
	{"HR", "Collect statutory details (KRA PIN, NSSF, SHIF)"},
	{"HR", "Collect bank / payment details"},
	{"HR", "Add employee to payroll"},
	{"Training", "Company orientation"},
	{"Training", "Role-specific training"},
	{"Training", "Safety & compliance induction"},
}

// ListOnboardings returns tenant-scoped onboardings (optionally for one employee).
func (s *Service) ListOnboardings(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.EmployeeOnboarding, error) {
	q := s.orm.EmployeeOnboarding.Query().Where(employeeonboarding.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(employeeonboarding.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(employeeonboarding.FieldCreatedAt)).All(ctx)
}

// StartOnboarding creates an onboarding for an employee and seeds the default checklist.
func (s *Service) StartOnboarding(ctx context.Context, tenantID, employeeID uuid.UUID) (*ent.EmployeeOnboarding, error) {
	if err := tenantref.Employee(ctx, s.orm, tenantID, "employee", &employeeID); err != nil {
		return nil, err
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	onb, err := seedOnboardingTx(ctx, tx, tenantID, employeeID)
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("recruitment: commit onboarding: %w", err)
	}
	return onb, nil
}

// seedOnboardingTx creates an in_progress onboarding + the default task checklist (tx-scoped).
func seedOnboardingTx(ctx context.Context, tx *ent.Tx, tenantID, employeeID uuid.UUID) (*ent.EmployeeOnboarding, error) {
	onb, err := tx.EmployeeOnboarding.Create().
		SetTenantID(tenantID).SetEmployeeID(employeeID).
		SetStatus(employeeonboarding.StatusInProgress).SetStartedAt(time.Now().UTC()).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: create onboarding: %w", err)
	}
	builders := make([]*ent.OnboardingTaskCreate, 0, len(defaultOnboardingTasks))
	for i, t := range defaultOnboardingTasks {
		builders = append(builders, tx.OnboardingTask.Create().
			SetTenantID(tenantID).SetOnboardingID(onb.ID).
			SetCategory(onboardingtask.Category(t.Category)).SetTitle(t.Title).SetOrder(i))
	}
	if _, err := tx.OnboardingTask.CreateBulk(builders...).Save(ctx); err != nil {
		return nil, fmt.Errorf("recruitment: seed onboarding tasks: %w", err)
	}
	return onb, nil
}

// ListTasks returns the checklist for a tenant-scoped onboarding.
func (s *Service) ListTasks(ctx context.Context, tenantID, onboardingID uuid.UUID) ([]*ent.OnboardingTask, error) {
	return s.orm.OnboardingTask.Query().
		Where(onboardingtask.TenantID(tenantID), onboardingtask.OnboardingID(onboardingID)).
		Order(ent.Asc(onboardingtask.FieldOrder)).All(ctx)
}

// CompleteTask marks a task done (or undone) and refreshes the onboarding status to
// completed when every task is done.
func (s *Service) CompleteTask(ctx context.Context, tenantID, taskID uuid.UUID, done bool) (*ent.OnboardingTask, error) {
	task, err := s.orm.OnboardingTask.Query().
		Where(onboardingtask.TenantID(tenantID), onboardingtask.ID(taskID)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: load task: %w", err)
	}
	u := task.Update().SetIsDone(done)
	if done {
		u = u.SetDoneAt(time.Now().UTC())
	} else {
		u = u.ClearDoneAt()
	}
	updated, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: complete task: %w", err)
	}
	if err := s.refreshOnboardingStatus(ctx, tenantID, task.OnboardingID); err != nil {
		return nil, err
	}
	return updated, nil
}

// TaskUpdate carries the editable scheduling fields of an onboarding task.
type TaskUpdate struct {
	AssignedTo *uuid.UUID
	DueDate    *time.Time
	ClearDue   bool
}

// UpdateTask sets a task's assignee and/or due date (for accountability + overdue tracking).
func (s *Service) UpdateTask(ctx context.Context, tenantID, taskID uuid.UUID, in TaskUpdate) (*ent.OnboardingTask, error) {
	task, err := s.orm.OnboardingTask.Query().
		Where(onboardingtask.TenantID(tenantID), onboardingtask.ID(taskID)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("recruitment: load task: %w", err)
	}
	u := task.Update()
	if in.AssignedTo != nil {
		if err := tenantref.Employee(ctx, s.orm, tenantID, "assignee", in.AssignedTo); err != nil {
			return nil, err
		}
		u = u.SetAssignedTo(*in.AssignedTo)
	}
	if in.ClearDue {
		u = u.ClearDueDate()
	} else if in.DueDate != nil {
		u = u.SetDueDate(*in.DueDate)
	}
	return u.Save(ctx)
}

// AddTask appends a custom task to an existing onboarding checklist (beyond the seeded defaults).
func (s *Service) AddTask(ctx context.Context, tenantID, onboardingID uuid.UUID, category, title string) (*ent.OnboardingTask, error) {
	if title == "" {
		return nil, fmt.Errorf("title is required")
	}
	if err := tenantref.Require(ctx, "onboarding", s.orm.EmployeeOnboarding.Query().
		Where(employeeonboarding.TenantID(tenantID), employeeonboarding.ID(onboardingID))); err != nil {
		return nil, err
	}
	if category == "" {
		category = "Other"
	}
	n, _ := s.orm.OnboardingTask.Query().
		Where(onboardingtask.TenantID(tenantID), onboardingtask.OnboardingID(onboardingID)).Count(ctx)
	return s.orm.OnboardingTask.Create().
		SetTenantID(tenantID).SetOnboardingID(onboardingID).
		SetCategory(onboardingtask.Category(category)).SetTitle(title).SetOrder(n).Save(ctx)
}

// refreshOnboardingStatus marks an onboarding completed when all its tasks are done.
func (s *Service) refreshOnboardingStatus(ctx context.Context, tenantID, onboardingID uuid.UUID) error {
	tasks, err := s.orm.OnboardingTask.Query().
		Where(onboardingtask.TenantID(tenantID), onboardingtask.OnboardingID(onboardingID)).All(ctx)
	if err != nil {
		return fmt.Errorf("recruitment: load tasks: %w", err)
	}
	if len(tasks) == 0 {
		return nil
	}
	for _, t := range tasks {
		if !t.IsDone {
			return nil
		}
	}
	if _, err := s.orm.EmployeeOnboarding.Update().
		Where(employeeonboarding.TenantID(tenantID), employeeonboarding.ID(onboardingID)).
		SetStatus(employeeonboarding.StatusCompleted).SetCompletedAt(time.Now().UTC()).Save(ctx); err != nil {
		return fmt.Errorf("recruitment: complete onboarding: %w", err)
	}
	return nil
}
