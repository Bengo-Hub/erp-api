// Package performance implements tenant-isolated performance management: metric
// categories/definitions, employee metric records, per-period targets, and reviews (FSM)
// with per-metric scores.
package performance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeemetric"
	"github.com/Bengo-Hub/erp-api/internal/ent/metriccategory"
	"github.com/Bengo-Hub/erp-api/internal/ent/performancemetric"
	"github.com/Bengo-Hub/erp-api/internal/platform/tenantref"
)

// Service holds performance CRUD + the review FSM. Tenant-scoped.
type Service struct {
	orm *ent.Client
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// ---- Categories ----

// ListCategories returns tenant-scoped metric categories.
func (s *Service) ListCategories(ctx context.Context, tenantID uuid.UUID) ([]*ent.MetricCategory, error) {
	return s.orm.MetricCategory.Query().
		Where(metriccategory.TenantID(tenantID)).
		Order(ent.Asc(metriccategory.FieldOrder)).All(ctx)
}

// CreateCategory inserts a tenant-scoped metric category.
func (s *Service) CreateCategory(ctx context.Context, tenantID uuid.UUID, name, description string, order int, createdBy *uuid.UUID) (*ent.MetricCategory, error) {
	b := s.orm.MetricCategory.Create().
		SetTenantID(tenantID).SetName(name).SetDescription(description).SetOrder(order).SetIsActive(true)
	if createdBy != nil {
		b = b.SetCreatedBy(*createdBy)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("performance: create category: %w", err)
	}
	return row, nil
}

// ---- Metrics ----

// ListMetrics returns metrics filtered by tenant (+ optional category).
func (s *Service) ListMetrics(ctx context.Context, tenantID uuid.UUID, categoryID *uuid.UUID) ([]*ent.PerformanceMetric, error) {
	q := s.orm.PerformanceMetric.Query().Where(performancemetric.TenantID(tenantID))
	if categoryID != nil {
		q = q.Where(performancemetric.CategoryID(*categoryID))
	}
	return q.Order(ent.Asc(performancemetric.FieldName)).All(ctx)
}

// MetricInput is the create payload for a performance metric.
type MetricInput struct {
	CategoryID  uuid.UUID
	Name        string
	Description string
	MetricType  string
	Unit        string
	MinValue    string
	MaxValue    string
	TargetValue string
	CreatedBy   *uuid.UUID
}

// CreateMetric inserts a tenant-scoped performance metric.
func (s *Service) CreateMetric(ctx context.Context, tenantID uuid.UUID, in MetricInput) (*ent.PerformanceMetric, error) {
	if err := tenantref.Require(ctx, "metric category", s.orm.MetricCategory.Query().
		Where(metriccategory.TenantID(tenantID), metriccategory.ID(in.CategoryID))); err != nil {
		return nil, err
	}
	b := s.orm.PerformanceMetric.Create().
		SetTenantID(tenantID).SetCategoryID(in.CategoryID).SetName(in.Name).
		SetDescription(in.Description).
		SetMetricType(performancemetric.MetricType(in.MetricType)).SetUnit(in.Unit).SetIsActive(true)
	if d, ok, err := optDecimal(in.MinValue); err != nil {
		return nil, fmt.Errorf("performance: min_value: %w", err)
	} else if ok {
		b = b.SetMinValue(d)
	}
	if d, ok, err := optDecimal(in.MaxValue); err != nil {
		return nil, fmt.Errorf("performance: max_value: %w", err)
	} else if ok {
		b = b.SetMaxValue(d)
	}
	if d, ok, err := optDecimal(in.TargetValue); err != nil {
		return nil, fmt.Errorf("performance: target_value: %w", err)
	} else if ok {
		b = b.SetTargetValue(d)
	}
	if in.CreatedBy != nil {
		b = b.SetCreatedBy(*in.CreatedBy)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("performance: create metric: %w", err)
	}
	return row, nil
}

// ---- Employee metrics ----

// ListEmployeeMetrics returns recorded metric values filtered by tenant (+ optional employee).
func (s *Service) ListEmployeeMetrics(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.EmployeeMetric, error) {
	q := s.orm.EmployeeMetric.Query().Where(employeemetric.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(employeemetric.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(employeemetric.FieldDateRecorded)).All(ctx)
}

// RecordMetricInput is the upsert payload for an employee metric value.
type RecordMetricInput struct {
	EmployeeID   uuid.UUID
	MetricID     uuid.UUID
	Value        string
	DateRecorded time.Time
	Notes        string
	RecordedBy   *uuid.UUID
}

// RecordEmployeeMetric upserts an employee's metric value for a date and projects a numeric
// value for numeric/percentage/rating metric types (port of EmployeeMetric.save).
func (s *Service) RecordEmployeeMetric(ctx context.Context, tenantID uuid.UUID, in RecordMetricInput) (*ent.EmployeeMetric, error) {
	if err := tenantref.Employee(ctx, s.orm, tenantID, "employee", &in.EmployeeID); err != nil {
		return nil, err
	}
	metric, err := s.orm.PerformanceMetric.Query().
		Where(performancemetric.TenantID(tenantID), performancemetric.ID(in.MetricID)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("performance: load metric: %w", err)
	}
	var numeric *decimal.Decimal
	switch metric.MetricType {
	case performancemetric.MetricTypeNumeric, performancemetric.MetricTypePercentage, performancemetric.MetricTypeRating:
		if d, derr := decimal.NewFromString(in.Value); derr == nil {
			numeric = &d
		}
	}

	existing, err := s.orm.EmployeeMetric.Query().Where(
		employeemetric.TenantID(tenantID),
		employeemetric.EmployeeID(in.EmployeeID),
		employeemetric.MetricID(in.MetricID),
		employeemetric.DateRecorded(in.DateRecorded),
	).First(ctx)
	if ent.IsNotFound(err) {
		b := s.orm.EmployeeMetric.Create().
			SetTenantID(tenantID).SetEmployeeID(in.EmployeeID).SetMetricID(in.MetricID).
			SetValue(in.Value).SetDateRecorded(in.DateRecorded).SetNotes(in.Notes)
		if numeric != nil {
			b = b.SetNumericValue(*numeric)
		}
		if in.RecordedBy != nil {
			b = b.SetRecordedBy(*in.RecordedBy)
		}
		row, cerr := b.Save(ctx)
		if cerr != nil {
			return nil, fmt.Errorf("performance: record metric: %w", cerr)
		}
		return row, nil
	}
	if err != nil {
		return nil, fmt.Errorf("performance: metric lookup: %w", err)
	}
	u := existing.Update().SetValue(in.Value).SetNotes(in.Notes)
	if numeric != nil {
		u = u.SetNumericValue(*numeric)
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("performance: update metric: %w", err)
	}
	return row, nil
}

// optDecimal parses an optional decimal: ("",false,nil) when empty.
func optDecimal(s string) (decimal.Decimal, bool, error) {
	if s == "" {
		return decimal.Zero, false, nil
	}
	d, err := decimal.NewFromString(s)
	if err != nil {
		return decimal.Zero, false, err
	}
	return d, true, nil
}
