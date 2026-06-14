package performance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/metrictarget"
	"github.com/Bengo-Hub/erp-api/internal/ent/performancereview"
	"github.com/Bengo-Hub/erp-api/internal/ent/reviewmetric"
)

// ---- Targets ----

// ListTargets returns targets filtered by tenant (+ optional employee).
func (s *Service) ListTargets(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.MetricTarget, error) {
	q := s.orm.MetricTarget.Query().Where(metrictarget.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(metrictarget.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(metrictarget.FieldPeriodStart)).All(ctx)
}

// SetTarget upserts a per-period target for an employee/metric.
func (s *Service) SetTarget(ctx context.Context, tenantID, employeeID, metricID uuid.UUID, target decimal.Decimal, start, end time.Time, createdBy *uuid.UUID) (*ent.MetricTarget, error) {
	existing, err := s.orm.MetricTarget.Query().Where(
		metrictarget.TenantID(tenantID),
		metrictarget.EmployeeID(employeeID),
		metrictarget.MetricID(metricID),
		metrictarget.PeriodStart(start),
		metrictarget.PeriodEnd(end),
	).First(ctx)
	if ent.IsNotFound(err) {
		b := s.orm.MetricTarget.Create().
			SetTenantID(tenantID).SetEmployeeID(employeeID).SetMetricID(metricID).
			SetTargetValue(target).SetPeriodStart(start).SetPeriodEnd(end).SetIsActive(true)
		if createdBy != nil {
			b = b.SetCreatedBy(*createdBy)
		}
		row, cerr := b.Save(ctx)
		if cerr != nil {
			return nil, fmt.Errorf("performance: set target: %w", cerr)
		}
		return row, nil
	}
	if err != nil {
		return nil, fmt.Errorf("performance: target lookup: %w", err)
	}
	return existing.Update().SetTargetValue(target).Save(ctx)
}

// ---- Reviews ----

// ListReviews returns reviews filtered by tenant (+ optional employee).
func (s *Service) ListReviews(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.PerformanceReview, error) {
	q := s.orm.PerformanceReview.Query().Where(performancereview.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(performancereview.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(performancereview.FieldReviewDate)).All(ctx)
}

// ReviewInput is the create payload for a performance review.
type ReviewInput struct {
	EmployeeID  uuid.UUID
	Title       string
	Description string
	ReviewDate  time.Time
	ReviewerID  *uuid.UUID
	CreatedBy   *uuid.UUID
}

// CreateReview opens a draft performance review.
func (s *Service) CreateReview(ctx context.Context, tenantID uuid.UUID, in ReviewInput) (*ent.PerformanceReview, error) {
	b := s.orm.PerformanceReview.Create().
		SetTenantID(tenantID).SetEmployeeID(in.EmployeeID).SetTitle(in.Title).
		SetDescription(in.Description).SetReviewDate(in.ReviewDate).
		SetStatus(performancereview.StatusDraft)
	if in.ReviewerID != nil {
		b = b.SetReviewerID(*in.ReviewerID)
	}
	if in.CreatedBy != nil {
		b = b.SetCreatedBy(*in.CreatedBy)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("performance: create review: %w", err)
	}
	return row, nil
}

// reviewTransitions defines the review FSM.
var reviewTransitions = map[performancereview.Status][]performancereview.Status{
	performancereview.StatusDraft:      {performancereview.StatusInProgress},
	performancereview.StatusInProgress: {performancereview.StatusCompleted},
	performancereview.StatusCompleted:  {performancereview.StatusApproved, performancereview.StatusRejected},
	performancereview.StatusApproved:   {},
	performancereview.StatusRejected:   {performancereview.StatusInProgress},
}

// SetReviewStatus transitions a review, rejecting invalid transitions; overallRating (0-5,
// optional) applied where supplied.
func (s *Service) SetReviewStatus(ctx context.Context, tenantID, id uuid.UUID, status, overallRating string) (*ent.PerformanceReview, error) {
	rv, err := s.orm.PerformanceReview.Query().
		Where(performancereview.TenantID(tenantID), performancereview.ID(id)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("performance: load review: %w", err)
	}
	target := performancereview.Status(status)
	ok := false
	for _, t := range reviewTransitions[rv.Status] {
		if t == target {
			ok = true
			break
		}
	}
	if !ok {
		return nil, fmt.Errorf("performance: invalid review transition %s -> %s", rv.Status, target)
	}
	u := rv.Update().SetStatus(target)
	if overallRating != "" {
		d, derr := decimal.NewFromString(overallRating)
		if derr != nil || d.LessThan(decimal.Zero) || d.GreaterThan(decimal.NewFromInt(5)) {
			return nil, fmt.Errorf("performance: overall_rating must be 0-5")
		}
		u = u.SetOverallRating(d)
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("performance: transition: %w", err)
	}
	return row, nil
}

// ---- Review metrics ----

// ListReviewMetrics returns the per-metric scores for a tenant-scoped review.
func (s *Service) ListReviewMetrics(ctx context.Context, tenantID, reviewID uuid.UUID) ([]*ent.ReviewMetric, error) {
	return s.orm.ReviewMetric.Query().
		Where(reviewmetric.TenantID(tenantID), reviewmetric.ReviewID(reviewID)).All(ctx)
}

// ReviewMetricInput is the upsert payload for a review metric score.
type ReviewMetricInput struct {
	ReviewID uuid.UUID
	MetricID uuid.UUID
	Value    string
	Rating   string
	Comments string
}

// UpsertReviewMetric records/updates a metric score within a review (unique per review/metric).
func (s *Service) UpsertReviewMetric(ctx context.Context, tenantID uuid.UUID, in ReviewMetricInput) (*ent.ReviewMetric, error) {
	var rating *decimal.Decimal
	if in.Rating != "" {
		d, derr := decimal.NewFromString(in.Rating)
		if derr != nil || d.LessThan(decimal.Zero) || d.GreaterThan(decimal.NewFromInt(5)) {
			return nil, fmt.Errorf("performance: rating must be 0-5")
		}
		rating = &d
	}
	existing, err := s.orm.ReviewMetric.Query().Where(
		reviewmetric.TenantID(tenantID),
		reviewmetric.ReviewID(in.ReviewID),
		reviewmetric.MetricID(in.MetricID),
	).First(ctx)
	if ent.IsNotFound(err) {
		b := s.orm.ReviewMetric.Create().
			SetTenantID(tenantID).SetReviewID(in.ReviewID).SetMetricID(in.MetricID).
			SetValue(in.Value).SetComments(in.Comments)
		if rating != nil {
			b = b.SetRating(*rating)
		}
		row, cerr := b.Save(ctx)
		if cerr != nil {
			return nil, fmt.Errorf("performance: create review metric: %w", cerr)
		}
		return row, nil
	}
	if err != nil {
		return nil, fmt.Errorf("performance: review metric lookup: %w", err)
	}
	u := existing.Update().SetValue(in.Value).SetComments(in.Comments)
	if rating != nil {
		u = u.SetRating(*rating)
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("performance: update review metric: %w", err)
	}
	return row, nil
}
