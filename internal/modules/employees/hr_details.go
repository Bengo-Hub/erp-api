package employees

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/department"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobtitle"
)

// HRInput carries the employment details kept in hr_details: department, job title, manager,
// employment type and date joined. Nil leaves a field unchanged; a pointer to uuid.Nil clears
// an id. Department-based reports, attendance rules and approvals read these.
type HRInput struct {
	DepartmentID   *uuid.UUID
	JobTitleID     *uuid.UUID
	ReportsToID    *uuid.UUID
	EmploymentType *string
	DateJoined     *time.Time
}

// Empty reports whether the input changes nothing.
func (in HRInput) Empty() bool {
	return in.DepartmentID == nil && in.JobTitleID == nil && in.ReportsToID == nil &&
		in.EmploymentType == nil && in.DateJoined == nil
}

var employmentTypes = map[string]bool{"permanent": true, "contract": true, "casual": true, "consultant": true, "intern": true}

// UpsertHR applies in to the employee's hr_details row, creating it when missing. Every id
// must belong to the tenant, and a person cannot report to themselves.
func (s *Service) UpsertHR(ctx context.Context, tenantID, empID uuid.UUID, in HRInput) error {
	if in.Empty() {
		return nil
	}
	set := func(id *uuid.UUID) bool { return id != nil && *id != uuid.Nil }
	if set(in.DepartmentID) {
		if ok, err := s.orm.Department.Query().Where(department.ID(*in.DepartmentID), department.TenantID(tenantID)).Exist(ctx); err != nil || !ok {
			return fmt.Errorf("department not found")
		}
	}
	if set(in.JobTitleID) {
		if ok, err := s.orm.JobTitle.Query().Where(jobtitle.ID(*in.JobTitleID), jobtitle.TenantID(tenantID)).Exist(ctx); err != nil || !ok {
			return fmt.Errorf("job title not found")
		}
	}
	if set(in.ReportsToID) {
		if *in.ReportsToID == empID {
			return fmt.Errorf("an employee cannot report to themselves")
		}
		if ok, err := s.orm.Employee.Query().Where(employee.ID(*in.ReportsToID), employee.TenantID(tenantID)).Exist(ctx); err != nil || !ok {
			return fmt.Errorf("manager not found")
		}
	}
	var empType string
	if in.EmploymentType != nil {
		empType = strings.ToLower(strings.TrimSpace(*in.EmploymentType))
		if empType != "" && !employmentTypes[empType] {
			return fmt.Errorf("employment_type must be permanent, contract, casual, consultant or intern")
		}
	}

	row, err := s.orm.HRDetails.Query().Where(hrdetails.TenantID(tenantID), hrdetails.EmployeeID(empID)).
		Order(ent.Desc(hrdetails.FieldUpdatedAt)).First(ctx)
	if ent.IsNotFound(err) {
		c := s.orm.HRDetails.Create().SetTenantID(tenantID).SetEmployeeID(empID)
		if set(in.DepartmentID) {
			c.SetDepartmentID(*in.DepartmentID)
		}
		if set(in.JobTitleID) {
			c.SetJobTitleID(*in.JobTitleID)
		}
		if set(in.ReportsToID) {
			c.SetReportsToID(*in.ReportsToID)
		}
		if in.EmploymentType != nil {
			c.SetEmploymentType(empType)
		}
		c.SetNillableDateJoined(in.DateJoined)
		return c.Exec(ctx)
	}
	if err != nil {
		return fmt.Errorf("load hr details: %w", err)
	}
	u := row.Update()
	applyID := func(id *uuid.UUID, setFn func(uuid.UUID), clearFn func()) {
		switch {
		case id == nil:
		case *id == uuid.Nil:
			clearFn()
		default:
			setFn(*id)
		}
	}
	applyID(in.DepartmentID, func(v uuid.UUID) { u.SetDepartmentID(v) }, func() { u.ClearDepartmentID() })
	applyID(in.JobTitleID, func(v uuid.UUID) { u.SetJobTitleID(v) }, func() { u.ClearJobTitleID() })
	applyID(in.ReportsToID, func(v uuid.UUID) { u.SetReportsToID(v) }, func() { u.ClearReportsToID() })
	if in.EmploymentType != nil {
		u.SetEmploymentType(empType)
	}
	if in.DateJoined != nil {
		u.SetDateJoined(*in.DateJoined)
	}
	return u.Exec(ctx)
}
