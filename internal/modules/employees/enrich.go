package employees

import (
	"context"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/authoutlet"
	"github.com/Bengo-Hub/erp-api/internal/ent/contactdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/department"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobgroup"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobtitle"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
)

// EmployeeView is an employee enriched with the hr_details-derived fields the UI lists/charts need
// (department/job-title NAMES, employment type, and the reporting manager). Embedding *ent.Employee
// promotes its JSON fields, so the response is a superset of the raw employee shape.
type EmployeeView struct {
	*ent.Employee
	DepartmentID   *uuid.UUID `json:"department_id,omitempty"`
	DepartmentName string     `json:"department_name,omitempty"`
	JobTitleID     *uuid.UUID `json:"job_title_id,omitempty"`
	JobTitleName   string     `json:"job_title_name,omitempty"`
	EmploymentType string     `json:"employment_type,omitempty"`
	// DateJoined is the hr_details date joined as YYYY-MM-DD (the form's date input format).
	DateJoined  string     `json:"date_joined,omitempty"`
	ReportsToID *uuid.UUID `json:"reports_to_id,omitempty"`
	ReportsTo   string     `json:"reports_to_name,omitempty"`
	// Manager mirrors reports_to_id so the org-chart (which reads `manager`) renders the tree.
	Manager *uuid.UUID `json:"manager,omitempty"`
	// Outlet is the branch/outlet NAME (resolved from the local AuthOutlet shadow), so the UI
	// never has to fall back to rendering the raw outlet_id uuid.
	Outlet string `json:"outlet,omitempty"`
	// PhoneNumber is the phone kept in contact_details (the employee form's phone_number).
	PhoneNumber string `json:"phone_number,omitempty"`
	// BasicSalary is the monthly salary from the active salary_details row (the Salary tab).
	BasicSalary *string `json:"basic_salary,omitempty"`
	// JobGroup is the salary_details job group as {id, name} (the UI's relation shape).
	JobGroup *NamedRef `json:"job_group,omitempty"`
	// MiddleName is kept in the employee's metadata (the table has first and last name only).
	MiddleName string `json:"middle_name,omitempty"`
	// Salary is the stored salary form. Set on a single employee read only, for callers who may
	// manage employees or see payroll.
	Salary *SalaryView `json:"salary,omitempty"`
}

// NamedRef is an id with its display name.
type NamedRef struct {
	ID   uuid.UUID `json:"id"`
	Name string    `json:"name"`
}

// Enrich attaches each employee's hr_details (department/job-title names, employment type, manager)
// in a single batched pass — no N+1. Tenant-scoped.
func (s *Service) Enrich(ctx context.Context, tenantID uuid.UUID, emps []*ent.Employee) ([]EmployeeView, error) {
	out := make([]EmployeeView, len(emps))
	for i, e := range emps {
		out[i] = EmployeeView{Employee: e}
		out[i].MiddleName, _ = e.Metadata[metaMiddleName].(string)
	}
	if len(emps) == 0 {
		return out, nil
	}
	ids := make([]uuid.UUID, len(emps))
	idx := make(map[uuid.UUID]int, len(emps))
	for i, e := range emps {
		ids[i] = e.ID
		idx[e.ID] = i
	}

	hrs, err := s.orm.HRDetails.Query().
		Where(hrdetails.TenantID(tenantID), hrdetails.EmployeeIDIn(ids...)).All(ctx)
	if err != nil {
		return nil, err
	}
	contacts, err := s.orm.ContactDetails.Query().
		Where(contactdetails.TenantID(tenantID), contactdetails.EmployeeIDIn(ids...), contactdetails.PhoneNotNil()).
		Order(ent.Asc(contactdetails.FieldUpdatedAt)).All(ctx)
	if err != nil {
		return nil, err
	}
	for _, c := range contacts { // ascending, so the latest row wins
		out[idx[c.EmployeeID]].PhoneNumber = *c.Phone
	}
	salaries, err := s.orm.SalaryDetails.Query().
		Where(salarydetails.TenantID(tenantID), salarydetails.EmployeeIDIn(ids...)).
		Order(ent.Asc(salarydetails.FieldIsActive), ent.Asc(salarydetails.FieldCreatedAt)).All(ctx)
	if err != nil {
		return nil, err
	}
	groupIDs := map[uuid.UUID]bool{}
	for _, sd := range salaries { // inactive first, so the newest active row (payroll's row) wins
		i := idx[sd.EmployeeID]
		if sd.IsActive {
			amount := sd.MonthlySalary.StringFixed(2)
			out[i].BasicSalary = &amount
		}
		out[i].JobGroup = nil
		if sd.JobGroupID != nil {
			out[i].JobGroup = &NamedRef{ID: *sd.JobGroupID}
			groupIDs[*sd.JobGroupID] = true
		}
	}
	if len(groupIDs) > 0 {
		groups, _ := s.orm.JobGroup.Query().Where(jobgroup.TenantID(tenantID), jobgroup.IDIn(keys(groupIDs)...)).All(ctx)
		groupName := make(map[uuid.UUID]string, len(groups))
		for _, g := range groups {
			groupName[g.ID] = g.Title
		}
		for i := range out {
			if out[i].JobGroup != nil {
				out[i].JobGroup.Name = groupName[out[i].JobGroup.ID]
			}
		}
	}
	outletIDs := map[uuid.UUID]bool{}
	for _, e := range emps {
		if e.OutletID != nil {
			outletIDs[*e.OutletID] = true
		}
	}
	outletName := s.outletNamesByID(ctx, keys(outletIDs))
	for i, e := range emps {
		if e.OutletID != nil {
			out[i].Outlet = outletName[*e.OutletID]
		}
	}

	deptIDs, titleIDs, mgrIDs := map[uuid.UUID]bool{}, map[uuid.UUID]bool{}, map[uuid.UUID]bool{}
	for _, h := range hrs {
		i := idx[h.EmployeeID]
		out[i].EmploymentType = h.EmploymentType
		if h.DateJoined != nil {
			out[i].DateJoined = h.DateJoined.Format("2006-01-02")
		}
		if h.DepartmentID != nil {
			out[i].DepartmentID = h.DepartmentID
			deptIDs[*h.DepartmentID] = true
		}
		if h.JobTitleID != nil {
			out[i].JobTitleID = h.JobTitleID
			titleIDs[*h.JobTitleID] = true
		}
		if h.ReportsToID != nil {
			out[i].ReportsToID = h.ReportsToID
			out[i].Manager = h.ReportsToID
			mgrIDs[*h.ReportsToID] = true
		}
	}

	deptName := s.namesByID(ctx, "department", keys(deptIDs))
	titleName := s.namesByID(ctx, "jobtitle", keys(titleIDs))
	mgrName := s.employeeNames(ctx, tenantID, keys(mgrIDs))
	for i := range out {
		if out[i].DepartmentID != nil {
			out[i].DepartmentName = deptName[*out[i].DepartmentID]
		}
		if out[i].JobTitleID != nil {
			out[i].JobTitleName = titleName[*out[i].JobTitleID]
		}
		if out[i].ReportsToID != nil {
			out[i].ReportsTo = mgrName[*out[i].ReportsToID]
		}
	}
	return out, nil
}

func keys(m map[uuid.UUID]bool) []uuid.UUID {
	out := make([]uuid.UUID, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

// namesByID loads title labels for departments or job titles.
func (s *Service) namesByID(ctx context.Context, kind string, ids []uuid.UUID) map[uuid.UUID]string {
	out := map[uuid.UUID]string{}
	if len(ids) == 0 {
		return out
	}
	switch kind {
	case "department":
		rows, _ := s.orm.Department.Query().Where(department.IDIn(ids...)).All(ctx)
		for _, d := range rows {
			out[d.ID] = d.Title
		}
	case "jobtitle":
		rows, _ := s.orm.JobTitle.Query().Where(jobtitle.IDIn(ids...)).All(ctx)
		for _, t := range rows {
			out[t.ID] = t.Title
		}
	}
	return out
}

// outletNamesByID resolves branch/outlet NAMEs from the local AuthOutlet shadow, so callers
// never have to fall back to rendering the raw outlet_id uuid.
func (s *Service) outletNamesByID(ctx context.Context, ids []uuid.UUID) map[uuid.UUID]string {
	out := map[uuid.UUID]string{}
	if len(ids) == 0 {
		return out
	}
	rows, _ := s.orm.AuthOutlet.Query().Where(authoutlet.IDIn(ids...)).All(ctx)
	for _, o := range rows {
		out[o.ID] = o.Name
	}
	return out
}

// employeeNames resolves "First Last" labels for a set of employee ids (e.g. managers).
func (s *Service) employeeNames(ctx context.Context, tenantID uuid.UUID, ids []uuid.UUID) map[uuid.UUID]string {
	out := map[uuid.UUID]string{}
	if len(ids) == 0 {
		return out
	}
	rows, _ := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(ids...)).All(ctx)
	for _, e := range rows {
		name := e.FirstName
		if e.LastName != "" {
			name = name + " " + e.LastName
		}
		out[e.ID] = name
	}
	return out
}
