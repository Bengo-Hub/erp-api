// Package training implements tenant-isolated training: courses, enrollments (with
// capacity enforcement), and post-course evaluations.
package training

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/trainingcourse"
	"github.com/Bengo-Hub/erp-api/internal/ent/trainingenrollment"
	"github.com/Bengo-Hub/erp-api/internal/ent/trainingevaluation"
	"github.com/Bengo-Hub/erp-api/internal/platform/tenantref"
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

// CourseInput is the create/update payload for a training course. Provider, Duration
// (hours), Cost and Status have no columns; they are kept in the course metadata.
type CourseInput struct {
	Title       string
	Description string
	StartDate   time.Time
	EndDate     time.Time
	Capacity    *int // nil keeps the stored value on update
	Provider    string
	Duration    string
	Cost        string
	Status      string
}

// CourseStatuses are the course states the screens offer.
var CourseStatuses = []string{"draft", "scheduled", "ongoing", "completed"}

// courseMetaKeys are the metadata keys CourseInput writes.
var courseMetaKeys = []string{"provider", "duration", "cost", "status"}

// validate checks dates, the numeric fields and the status.
func (in CourseInput) validate() error {
	if strings.TrimSpace(in.Title) == "" {
		return fmt.Errorf("training: title is required")
	}
	if in.EndDate.Before(in.StartDate) {
		return fmt.Errorf("training: end_date before start_date")
	}
	for name, v := range map[string]string{"duration": in.Duration, "cost": in.Cost} {
		if v == "" {
			continue
		}
		d, err := decimal.NewFromString(v)
		if err != nil || d.IsNegative() {
			return fmt.Errorf("training: %s must be a number of zero or more", name)
		}
	}
	if in.Status != "" && !slices.Contains(CourseStatuses, in.Status) {
		return fmt.Errorf("training: status must be one of %s", strings.Join(CourseStatuses, ", "))
	}
	return nil
}

// metadata merges the input's provider, duration, cost and status into existing
// metadata (other keys are kept; a blank value removes its key).
func (in CourseInput) metadata(existing map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range existing {
		out[k] = v
	}
	vals := map[string]string{"provider": strings.TrimSpace(in.Provider), "duration": in.Duration, "cost": in.Cost, "status": in.Status}
	for _, k := range courseMetaKeys {
		if vals[k] == "" {
			delete(out, k)
		} else {
			out[k] = vals[k]
		}
	}
	return out
}

// CreateCourse inserts a tenant-scoped training course.
func (s *Service) CreateCourse(ctx context.Context, tenantID uuid.UUID, in CourseInput) (*ent.TrainingCourse, error) {
	if in.Status == "" {
		in.Status = "draft"
	}
	if err := in.validate(); err != nil {
		return nil, err
	}
	row, err := s.orm.TrainingCourse.Create().
		SetTenantID(tenantID).SetTitle(in.Title).SetDescription(in.Description).
		SetStartDate(in.StartDate).SetEndDate(in.EndDate).SetNillableCapacity(in.Capacity).
		SetMetadata(in.metadata(nil)).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: create course: %w", err)
	}
	return row, nil
}

// UpdateCourse replaces a tenant-scoped course's details.
func (s *Service) UpdateCourse(ctx context.Context, tenantID, id uuid.UUID, in CourseInput) (*ent.TrainingCourse, error) {
	if in.Status == "" {
		in.Status = "draft"
	}
	if err := in.validate(); err != nil {
		return nil, err
	}
	c, err := s.orm.TrainingCourse.Query().
		Where(trainingcourse.TenantID(tenantID), trainingcourse.ID(id)).Only(ctx)
	if err != nil {
		return nil, err
	}
	row, err := c.Update().SetTitle(in.Title).SetDescription(in.Description).
		SetStartDate(in.StartDate).SetEndDate(in.EndDate).SetNillableCapacity(in.Capacity).
		SetMetadata(in.metadata(c.Metadata)).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: update course: %w", err)
	}
	return row, nil
}

// CourseView is a course with its metadata fields at the top level, named as the screens
// name them.
type CourseView struct {
	*ent.TrainingCourse
	Provider string `json:"provider,omitempty"`
	Duration string `json:"duration,omitempty"`
	Cost     string `json:"cost,omitempty"`
	Status   string `json:"status"`
}

// ViewCourse flattens a course's metadata.
func ViewCourse(c *ent.TrainingCourse) CourseView {
	str := func(k string) string {
		if v, ok := c.Metadata[k]; ok && v != nil {
			return fmt.Sprint(v)
		}
		return ""
	}
	v := CourseView{TrainingCourse: c, Provider: str("provider"), Duration: str("duration"), Cost: str("cost"), Status: str("status")}
	if v.Status == "" {
		v.Status = "draft"
	}
	return v
}

// namesRef carries the employee's name and the course title (as course_name, the name the
// screens read) for an enrolment or evaluation.
type namesRef struct {
	EmployeeName string `json:"employee_name,omitempty"`
	CourseName   string `json:"course_name,omitempty"`
}

// EnrollmentView is an enrolment with the employee's name and the course title.
type EnrollmentView struct {
	*ent.TrainingEnrollment
	namesRef
}

// EvaluationView is an evaluation with the employee's name and the course title.
type EvaluationView struct {
	*ent.TrainingEvaluation
	namesRef
}

// lookupNames loads employee names and course titles for the given ids (one query each).
func (s *Service) lookupNames(ctx context.Context, tenantID uuid.UUID, empIDs, courseIDs []uuid.UUID) (map[uuid.UUID]string, map[uuid.UUID]string, error) {
	emps := map[uuid.UUID]string{}
	courses := map[uuid.UUID]string{}
	if len(empIDs) > 0 {
		rows, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(empIDs...)).All(ctx)
		if err != nil {
			return nil, nil, fmt.Errorf("training: load employees: %w", err)
		}
		for _, e := range rows {
			emps[e.ID] = strings.TrimSpace(e.FirstName + " " + e.LastName)
		}
	}
	if len(courseIDs) > 0 {
		rows, err := s.orm.TrainingCourse.Query().Where(trainingcourse.TenantID(tenantID), trainingcourse.IDIn(courseIDs...)).All(ctx)
		if err != nil {
			return nil, nil, fmt.Errorf("training: load courses: %w", err)
		}
		for _, c := range rows {
			courses[c.ID] = c.Title
		}
	}
	return emps, courses, nil
}

// DescribeEnrollments adds employee names and course titles to enrolments.
func (s *Service) DescribeEnrollments(ctx context.Context, tenantID uuid.UUID, rows []*ent.TrainingEnrollment) ([]EnrollmentView, error) {
	empIDs, courseIDs := make([]uuid.UUID, len(rows)), make([]uuid.UUID, len(rows))
	for i, r := range rows {
		empIDs[i], courseIDs[i] = r.EmployeeID, r.CourseID
	}
	emps, courses, err := s.lookupNames(ctx, tenantID, empIDs, courseIDs)
	if err != nil {
		return nil, err
	}
	out := make([]EnrollmentView, len(rows))
	for i, r := range rows {
		out[i] = EnrollmentView{TrainingEnrollment: r, namesRef: namesRef{EmployeeName: emps[r.EmployeeID], CourseName: courses[r.CourseID]}}
	}
	return out, nil
}

// DescribeEvaluations adds employee names and course titles to evaluations.
func (s *Service) DescribeEvaluations(ctx context.Context, tenantID uuid.UUID, rows []*ent.TrainingEvaluation) ([]EvaluationView, error) {
	empIDs, courseIDs := make([]uuid.UUID, len(rows)), make([]uuid.UUID, len(rows))
	for i, r := range rows {
		empIDs[i], courseIDs[i] = r.EmployeeID, r.CourseID
	}
	emps, courses, err := s.lookupNames(ctx, tenantID, empIDs, courseIDs)
	if err != nil {
		return nil, err
	}
	out := make([]EvaluationView, len(rows))
	for i, r := range rows {
		out[i] = EvaluationView{TrainingEvaluation: r, namesRef: namesRef{EmployeeName: emps[r.EmployeeID], CourseName: courses[r.CourseID]}}
	}
	return out, nil
}

// ErrCourseInUse is returned when a course that still has enrolments is deleted.
var ErrCourseInUse = errors.New("this course has enrolments; delete them first or deactivate the course instead")

// DeleteCourse removes a tenant-scoped training course that has no enrolments (ErrCourseInUse
// otherwise).
func (s *Service) DeleteCourse(ctx context.Context, tenantID, id uuid.UUID) error {
	c, err := s.orm.TrainingCourse.Query().
		Where(trainingcourse.TenantID(tenantID), trainingcourse.ID(id)).Only(ctx)
	if err != nil {
		return err
	}
	used, err := s.orm.TrainingEnrollment.Query().
		Where(trainingenrollment.TenantID(tenantID), trainingenrollment.CourseID(c.ID)).Exist(ctx)
	if err != nil {
		return fmt.Errorf("training: check course enrolments: %w", err)
	}
	if used {
		return ErrCourseInUse
	}
	if err := s.orm.TrainingCourse.DeleteOne(c).Exec(ctx); err != nil {
		return fmt.Errorf("training: delete course: %w", err)
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
	if err := tenantref.Employee(ctx, s.orm, tenantID, "employee", &employeeID); err != nil {
		return nil, err
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := checkSeat(ctx, tx, tenantID, courseID); err != nil {
		return nil, err
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

// checkSeat loads a tenant course and refuses when its active enrolments already fill its
// capacity (0 = unlimited).
func checkSeat(ctx context.Context, tx *ent.Tx, tenantID, courseID uuid.UUID) error {
	course, err := tx.TrainingCourse.Query().
		Where(trainingcourse.TenantID(tenantID), trainingcourse.ID(courseID)).Only(ctx)
	if err != nil {
		return fmt.Errorf("training: load course: %w", err)
	}
	if course.Capacity <= 0 {
		return nil
	}
	enrolled, err := tx.TrainingEnrollment.Query().Where(
		trainingenrollment.TenantID(tenantID),
		trainingenrollment.CourseID(courseID),
		trainingenrollment.StatusEQ(trainingenrollment.StatusEnrolled),
	).Count(ctx)
	if err != nil {
		return fmt.Errorf("training: count enrolled: %w", err)
	}
	if enrolled >= course.Capacity {
		return fmt.Errorf("training: course is at capacity (%d)", course.Capacity)
	}
	return nil
}

// ErrEnrollmentEvaluated is returned when an enrolment whose employee already evaluated the
// course is moved or deleted (the evaluation would no longer match an enrolment).
var ErrEnrollmentEvaluated = errors.New("this enrolment already has an evaluation; delete the evaluation first")

// hasEvaluation reports whether the employee evaluated the course.
func hasEvaluation(ctx context.Context, c *ent.Client, tenantID, courseID, employeeID uuid.UUID) (bool, error) {
	ok, err := c.TrainingEvaluation.Query().Where(
		trainingevaluation.TenantID(tenantID), trainingevaluation.CourseID(courseID),
		trainingevaluation.EmployeeID(employeeID),
	).Exist(ctx)
	if err != nil {
		return false, fmt.Errorf("training: check evaluations: %w", err)
	}
	return ok, nil
}

// UpdateEnrollment moves an enrolment to another course and/or employee. A new course must
// have a free seat while the enrolment is active, and an evaluated enrolment cannot move.
func (s *Service) UpdateEnrollment(ctx context.Context, tenantID, id, courseID, employeeID uuid.UUID) (*ent.TrainingEnrollment, error) {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	e, err := tx.TrainingEnrollment.Query().
		Where(trainingenrollment.TenantID(tenantID), trainingenrollment.ID(id)).Only(ctx)
	if err != nil {
		return nil, err
	}
	if e.CourseID == courseID && e.EmployeeID == employeeID {
		return e, nil
	}
	if evaluated, err := hasEvaluation(ctx, tx.Client(), tenantID, e.CourseID, e.EmployeeID); err != nil {
		return nil, err
	} else if evaluated {
		return nil, ErrEnrollmentEvaluated
	}
	if ok, err := tx.Employee.Query().Where(employee.TenantID(tenantID), employee.ID(employeeID)).Exist(ctx); err != nil {
		return nil, fmt.Errorf("training: check employee: %w", err)
	} else if !ok {
		return nil, fmt.Errorf("training: employee not found")
	}
	if e.CourseID != courseID && e.Status == trainingenrollment.StatusEnrolled {
		if err := checkSeat(ctx, tx, tenantID, courseID); err != nil {
			return nil, err
		}
	} else if e.CourseID != courseID {
		if _, err := tx.TrainingCourse.Query().
			Where(trainingcourse.TenantID(tenantID), trainingcourse.ID(courseID)).Only(ctx); err != nil {
			return nil, fmt.Errorf("training: load course: %w", err)
		}
	}
	row, err := e.Update().SetCourseID(courseID).SetEmployeeID(employeeID).Save(ctx)
	if err != nil {
		if ent.IsConstraintError(err) {
			return nil, fmt.Errorf("training: the employee is already enrolled on that course")
		}
		return nil, fmt.Errorf("training: update enrollment: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("training: commit enrollment: %w", err)
	}
	return row, nil
}

// DeleteEnrollment removes an enrolment whose employee has not evaluated the course.
func (s *Service) DeleteEnrollment(ctx context.Context, tenantID, id uuid.UUID) error {
	e, err := s.orm.TrainingEnrollment.Query().
		Where(trainingenrollment.TenantID(tenantID), trainingenrollment.ID(id)).Only(ctx)
	if err != nil {
		return err
	}
	if evaluated, err := hasEvaluation(ctx, s.orm, tenantID, e.CourseID, e.EmployeeID); err != nil {
		return err
	} else if evaluated {
		return ErrEnrollmentEvaluated
	}
	if err := s.orm.TrainingEnrollment.DeleteOne(e).Exec(ctx); err != nil {
		return fmt.Errorf("training: delete enrollment: %w", err)
	}
	return nil
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

// ErrNotEnrolled is returned when an evaluation names an employee who is not enrolled on
// the course (or whose enrolment was cancelled).
var ErrNotEnrolled = errors.New("training: the employee is not enrolled on this course")

// CreateEvaluation records an employee's post-course evaluation (rating clamped 0-5).
func (s *Service) CreateEvaluation(ctx context.Context, tenantID, courseID, employeeID uuid.UUID, rating int, feedback string) (*ent.TrainingEvaluation, error) {
	rating = clampRating(rating)
	// Only someone enrolled on the course can evaluate it.
	enrolled, err := s.orm.TrainingEnrollment.Query().Where(
		trainingenrollment.TenantID(tenantID), trainingenrollment.CourseID(courseID),
		trainingenrollment.EmployeeID(employeeID),
		trainingenrollment.StatusNEQ(trainingenrollment.StatusCancelled),
	).Exist(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: check enrolment: %w", err)
	}
	if !enrolled {
		return nil, ErrNotEnrolled
	}
	row, err := s.orm.TrainingEvaluation.Create().
		SetTenantID(tenantID).SetCourseID(courseID).SetEmployeeID(employeeID).
		SetRating(rating).SetFeedback(feedback).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: create evaluation: %w", err)
	}
	return row, nil
}

// clampRating keeps a rating within 0-5.
func clampRating(rating int) int {
	return min(max(rating, 0), 5)
}

// UpdateEvaluation changes an evaluation's rating (clamped 0-5) and feedback; the course and
// employee stay those of the enrolment it was recorded for.
func (s *Service) UpdateEvaluation(ctx context.Context, tenantID, id uuid.UUID, rating int, feedback string) (*ent.TrainingEvaluation, error) {
	ev, err := s.orm.TrainingEvaluation.Query().
		Where(trainingevaluation.TenantID(tenantID), trainingevaluation.ID(id)).Only(ctx)
	if err != nil {
		return nil, err
	}
	row, err := ev.Update().SetRating(clampRating(rating)).SetFeedback(feedback).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("training: update evaluation: %w", err)
	}
	return row, nil
}

// DeleteEvaluation removes a tenant-scoped evaluation (nothing else refers to it).
func (s *Service) DeleteEvaluation(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.TrainingEvaluation.Delete().
		Where(trainingevaluation.TenantID(tenantID), trainingevaluation.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("training: delete evaluation: %w", err)
	}
	if n == 0 {
		return &ent.NotFoundError{}
	}
	return nil
}
