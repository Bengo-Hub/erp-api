package orgsettings

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	sharedcache "github.com/Bengo-Hub/cache"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/department"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeprojectallocation"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

// Treasury owns cost centres. A department (or project allocation) stores the id of one of the
// tenant's treasury cost centres; it is checked when saved and every night afterwards.

// ErrUnknownCostCenter is returned when a cost centre id is not an active cost centre of the
// tenant in treasury.
var ErrUnknownCostCenter = errors.New("cost centre is not an active cost centre of this organisation in treasury")

// CostCenterSource lists a tenant's treasury cost centres (treasury.Client).
type CostCenterSource interface {
	ListCostCenters(ctx context.Context, tenantID uuid.UUID) ([]treasury.CostCenter, error)
}

// WithCostCenters enables the cost centre check on save.
func (s *Service) WithCostCenters(src CostCenterSource, log *zap.Logger) *Service {
	s.costCenters, s.log = src, log
	return s
}

// checkCostCenter refuses an id that treasury does not list as an active cost centre of the
// tenant. When treasury cannot be reached the save goes ahead (HR work never waits on treasury)
// and the nightly check reports the id if it turns out to be wrong.
func (s *Service) checkCostCenter(ctx context.Context, tenantID uuid.UUID, id *uuid.UUID) error {
	if id == nil || s.costCenters == nil {
		return nil
	}
	centers, err := s.costCenters.ListCostCenters(ctx, tenantID)
	if err != nil {
		if s.log != nil {
			s.log.Warn("cost centre not checked: treasury unavailable", zap.String("tenant_id", tenantID.String()), zap.Error(err))
		}
		return nil
	}
	for _, c := range centers {
		if c.ID == *id && c.IsActive {
			return nil
		}
	}
	return ErrUnknownCostCenter
}

// CostCenterCheckKey is the app setting holding a tenant's last cost centre check.
const CostCenterCheckKey = "orgsettings.cost_center_check"

// CostCenterProblem is one stored cost centre id that is no longer an active treasury cost centre.
type CostCenterProblem struct {
	Record       string    `json:"record"` // department | project_allocation
	RecordID     uuid.UUID `json:"record_id"`
	Name         string    `json:"name"`
	CostCenterID uuid.UUID `json:"cost_center_id"`
	Reason       string    `json:"reason"` // missing | inactive
}

// CostCenterCheck is the result of the last check for a tenant.
type CostCenterCheck struct {
	CheckedAt time.Time           `json:"checked_at"`
	Problems  []CostCenterProblem `json:"problems"`
	Error     string              `json:"error,omitempty"`
}

// LastCostCenterCheck returns the tenant's last stored check (zero value when never run).
func (s *Service) LastCostCenterCheck(ctx context.Context, tenantID uuid.UUID) (CostCenterCheck, error) {
	var out CostCenterCheck
	row, err := s.orm.AppSetting.Query().Where(appsetting.TenantID(tenantID), appsetting.AppKey(CostCenterCheckKey)).Only(ctx)
	if ent.IsNotFound(err) {
		return out, nil
	}
	if err != nil {
		return out, err
	}
	err = json.Unmarshal([]byte(row.Value), &out)
	return out, err
}

// CheckTenantCostCenters compares the tenant's stored cost centre ids with treasury and stores
// the result. A treasury error is stored too, so a failed check is visible.
func (s *Service) CheckTenantCostCenters(ctx context.Context, tenantID uuid.UUID) (CostCenterCheck, error) {
	res := CostCenterCheck{CheckedAt: time.Now().UTC(), Problems: []CostCenterProblem{}}
	centers, err := s.costCenters.ListCostCenters(ctx, tenantID)
	if err != nil {
		res.Error = err.Error()
		return res, s.saveCheck(ctx, tenantID, res)
	}
	active := map[uuid.UUID]bool{}
	for _, c := range centers {
		active[c.ID] = c.IsActive
	}
	reason := func(id uuid.UUID) string {
		isActive, known := active[id]
		switch {
		case !known:
			return "missing"
		case !isActive:
			return "inactive"
		}
		return ""
	}
	depts, err := s.orm.Department.Query().Where(department.TenantID(tenantID), department.CostCenterIDNotNil()).All(ctx)
	if err != nil {
		return res, err
	}
	for _, d := range depts {
		if r := reason(*d.CostCenterID); r != "" {
			res.Problems = append(res.Problems, CostCenterProblem{Record: "department", RecordID: d.ID, Name: d.Title, CostCenterID: *d.CostCenterID, Reason: r})
		}
	}
	allocs, err := s.orm.EmployeeProjectAllocation.Query().Where(employeeprojectallocation.TenantID(tenantID),
		employeeprojectallocation.CostCenterIDNotNil(), employeeprojectallocation.IsActive(true)).All(ctx)
	if err != nil {
		return res, err
	}
	for _, a := range allocs {
		if r := reason(*a.CostCenterID); r != "" {
			res.Problems = append(res.Problems, CostCenterProblem{Record: "project_allocation", RecordID: a.ID, Name: a.ProjectName, CostCenterID: *a.CostCenterID, Reason: r})
		}
	}
	return res, s.saveCheck(ctx, tenantID, res)
}

func (s *Service) saveCheck(ctx context.Context, tenantID uuid.UUID, res CostCenterCheck) error {
	raw, err := json.Marshal(res)
	if err != nil {
		return err
	}
	return s.orm.AppSetting.Create().SetTenantID(tenantID).SetAppKey(CostCenterCheckKey).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).UpdateNewValues().Exec(ctx)
}

// tenantsWithCostCenters are the tenants holding at least one cost centre id.
func (s *Service) tenantsWithCostCenters(ctx context.Context) ([]uuid.UUID, error) {
	seen := map[uuid.UUID]bool{}
	var depts, allocs []uuid.UUID
	if err := s.orm.Department.Query().Where(department.CostCenterIDNotNil(), department.TenantIDNotNil()).
		Unique(true).Select(department.FieldTenantID).Scan(ctx, &depts); err != nil {
		return nil, err
	}
	if err := s.orm.EmployeeProjectAllocation.Query().Where(employeeprojectallocation.CostCenterIDNotNil()).
		Unique(true).Select(employeeprojectallocation.FieldTenantID).Scan(ctx, &allocs); err != nil {
		return nil, err
	}
	out := []uuid.UUID{}
	for _, id := range append(depts, allocs...) {
		if !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out, nil
}

// CostCenterCron checks every tenant's cost centre ids once a day, on one replica.
type CostCenterCron struct {
	svc      *Service
	log      *zap.Logger
	interval time.Duration
	// perTenant bounds each tenant's check (treasury call and writes).
	perTenant time.Duration
}

// NewCostCenterCron builds the nightly check; interval <= 0 means 24h.
func NewCostCenterCron(svc *Service, log *zap.Logger, interval time.Duration) *CostCenterCron {
	if interval <= 0 {
		interval = 24 * time.Hour
	}
	return &CostCenterCron{svc: svc, log: log.Named("orgsettings.cost_center_cron"), interval: interval, perTenant: 30 * time.Second}
}

// Start runs the check on a ticker until ctx ends.
func (c *CostCenterCron) Start(ctx context.Context) {
	if c.svc.costCenters == nil {
		c.log.Warn("cost centre check disabled: treasury not configured")
		return
	}
	go func() {
		ticker := time.NewTicker(time.Hour)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				// Every replica ticks hourly; only the first to claim the day runs it.
				if sharedcache.ClaimPeriod(ctx, "erp:cost-centre-check", c.interval) {
					c.RunOnce(ctx)
				}
			}
		}
	}()
}

// RunOnce checks every tenant that holds cost centre ids. One tenant's failure does not stop
// the others; it is stored on that tenant's check.
func (c *CostCenterCron) RunOnce(ctx context.Context) {
	tenants, err := c.svc.tenantsWithCostCenters(ctx)
	if err != nil {
		c.log.Error("cost centre check: list tenants", zap.Error(err))
		return
	}
	problems := 0
	for _, t := range tenants {
		if ctx.Err() != nil {
			return
		}
		tctx, cancel := context.WithTimeout(ctx, c.perTenant)
		res, err := c.svc.CheckTenantCostCenters(tctx, t)
		cancel()
		if err != nil {
			c.log.Error("cost centre check failed", zap.String("tenant_id", t.String()), zap.Error(err))
			continue
		}
		problems += len(res.Problems)
		if res.Error != "" || len(res.Problems) > 0 {
			c.log.Warn("cost centre check found problems", zap.String("tenant_id", t.String()),
				zap.Int("problems", len(res.Problems)), zap.String("treasury_error", res.Error))
		}
	}
	c.log.Info("cost centre check done", zap.Int("tenants", len(tenants)), zap.Int("problems", problems))
}

// String renders a problem for logs.
func (p CostCenterProblem) String() string {
	return fmt.Sprintf("%s %s (%s): cost centre %s %s", p.Record, p.RecordID, p.Name, p.CostCenterID, p.Reason)
}
