// Package training implements tenant-isolated training: courses, enrollments (with
// capacity enforcement), and post-course evaluations.
package training

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/trainingcourse"
	"github.com/Bengo-Hub/erp-api/internal/ent/trainingenrollment"
	"github.com/Bengo-Hub/erp-api/internal/ent/trainingevaluation"
)

// Service holds training CRUD + capacity-checked enrollment. Tenant-scoped.
type Service struct {
	orm *ent.Client
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// ---- Courses ----

// ListCourses returns tenant-scoped training courses.
func (s *Service) ListCourses(ctx context.Context, tenantID uuid.UUID) ([]*ent.TrainingCourse, error) {
	return s.orm.TrainingCourse.Query().
		Where(trainingcourse.TenantID(tenantID)).
		Order(ent.Desc(trainingcourse.FieldStartDate)).All(ctx)
}

// CourseInput is the create payload for a training course.
type CourseInput struct {
	Title       string
	Description string
	StartDate   time.Time
	EndDate     time.Time
	Capacity    int
}

// CreateCourse inserts a tenant-scoped training course.
func (s *Service) CreateCourse(ctx context.Context, tenantID uuid.UUID, in CourseInput) (*ent.TrainingCourse, error) {
	if in.EndDate.Before(in.StartDate) {
		return nil, fmt.Errorf("training: end_date before start_date")
	}
	row, err := s.orm.TrainingCourse.Create().
		SetTenantID(tenantID).SetTitle(in.Title).SetDescription(in.Description).
		SetStartDate(in.StartDate).SetEndDate(in.EndDate).SetCapacity(in.Capacity).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: create course: %w", err)
	}
	return row, nil
}

// DeleteCourse removes a tenant-scoped training course.
func (s *Service) DeleteCourse(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.TrainingCourse.Delete().
		Where(trainingcourse.TenantID(tenantID), trainingcourse.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("training: delete course: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("training: course not found")
	}
	return nil
}

// ---- Enrollments ----

// ListEnrollments returns enrollments filtered by tenant (+ optional course).
func (s *Service) ListEnrollments(ctx context.Context, tenantID uuid.UUID, courseID *uuid.UUID) ([]*ent.TrainingEnrollment, error) {
	q := s.orm.TrainingEnrollment.Query().Where(trainingenrollment.TenantID(tenantID))
	if courseID != nil {
		q = q.Where(trainingenrollment.CourseID(*courseID))
	}
	return q.Order(ent.Desc(trainingenrollment.FieldEnrolledAt)).All(ctx)
}

// Enroll enrolls an employee in a course, enforcing capacity (count active enrolled <
// course.capacity; 0 = unlimited) and the unique (tenant, course, employee) constraint.
func (s *Service) Enroll(ctx context.Context, tenantID, courseID, employeeID uuid.UUID) (*ent.TrainingEnrollment, error) {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	course, err := tx.TrainingCourse.Query().
		Where(trainingcourse.TenantID(tenantID), trainingcourse.ID(courseID)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: load course: %w", err)
	}
	if course.Capacity > 0 {
		enrolled, cerr := tx.TrainingEnrollment.Query().Where(
			trainingenrollment.TenantID(tenantID),
			trainingenrollment.CourseID(courseID),
			trainingenrollment.StatusEQ(trainingenrollment.StatusEnrolled),
		).Count(ctx)
		if cerr != nil {
			return nil, fmt.Errorf("training: count enrolled: %w", cerr)
		}
		if enrolled >= course.Capacity {
			return nil, fmt.Errorf("training: course is at capacity (%d)", course.Capacity)
		}
	}
	row, err := tx.TrainingEnrollment.Create().
		SetTenantID(tenantID).SetCourseID(courseID).SetEmployeeID(employeeID).
		SetStatus(trainingenrollment.StatusEnrolled).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: enroll: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("training: commit enroll: %w", err)
	}
	return row, nil
}

// SetEnrollmentStatus updates an enrollment's status (enrolled|completed|cancelled).
func (s *Service) SetEnrollmentStatus(ctx context.Context, tenantID, id uuid.UUID, status string) (*ent.TrainingEnrollment, error) {
	n, err := s.orm.TrainingEnrollment.Update().
		Where(trainingenrollment.TenantID(tenantID), trainingenrollment.ID(id)).
		SetStatus(trainingenrollment.Status(status)).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: update enrollment: %w", err)
	}
	if n == 0 {
		return nil, fmt.Errorf("training: enrollment not found")
	}
	return s.orm.TrainingEnrollment.Query().
		Where(trainingenrollment.TenantID(tenantID), trainingenrollment.ID(id)).Only(ctx)
}

// ---- Evaluations ----

// ListEvaluations returns evaluations filtered by tenant (+ optional course).
func (s *Service) ListEvaluations(ctx context.Context, tenantID uuid.UUID, courseID *uuid.UUID) ([]*ent.TrainingEvaluation, error) {
	q := s.orm.TrainingEvaluation.Query().Where(trainingevaluation.TenantID(tenantID))
	if courseID != nil {
		q = q.Where(trainingevaluation.CourseID(*courseID))
	}
	return q.Order(ent.Desc(trainingevaluation.FieldCreatedAt)).All(ctx)
}

// CreateEvaluation records an employee's post-course evaluation (rating clamped 0-5).
func (s *Service) CreateEvaluation(ctx context.Context, tenantID, courseID, employeeID uuid.UUID, rating int, feedback string) (*ent.TrainingEvaluation, error) {
	if rating < 0 {
		rating = 0
	}
	if rating > 5 {
		rating = 5
	}
	row, err := s.orm.TrainingEvaluation.Create().
		SetTenantID(tenantID).SetCourseID(courseID).SetEmployeeID(employeeID).
		SetRating(rating).SetFeedback(feedback).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: create evaluation: %w", err)
	}
	return row, nil
}
