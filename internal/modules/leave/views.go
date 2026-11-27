package leave

import (
	"context"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
)

// leaveNames holds display names for a page of leave rows, resolved in one query per kind.
type leaveNames struct {
	employee       map[uuid.UUID]string
	employeeNumber map[uuid.UUID]string
	category       map[uuid.UUID]string
}

// lookupNames resolves employee names and numbers and leave category names for the given ids.
func (s *Service) lookupNames(ctx context.Context, tenantID uuid.UUID, empIDs, catIDs []uuid.UUID) (leaveNames, error) {
	n := leaveNames{employee: map[uuid.UUID]string{}, employeeNumber: map[uuid.UUID]string{}, category: map[uuid.UUID]string{}}
	if len(empIDs) > 0 {
		emps, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(empIDs...)).
			Select(employee.FieldID, employee.FieldFirstName, employee.FieldLastName, employee.FieldEmployeeNumber).All(ctx)
		if err != nil {
			return n, fmt.Errorf("leave: load employees: %w", err)
		}
		for _, e := range emps {
			n.employee[e.ID] = strings.TrimSpace(e.FirstName + " " + e.LastName)
			if e.EmployeeNumber != nil {
				n.employeeNumber[e.ID] = *e.EmployeeNumber
			}
		}
	}
	if len(catIDs) > 0 {
		cats, err := s.orm.LeaveCategory.Query().Where(leavecategory.IDIn(catIDs...), leavecategory.TenantIDIn(tenantID, s.systemTenant)).
			Select(leavecategory.FieldID, leavecategory.FieldName).All(ctx)
		if err != nil {
			return n, fmt.Errorf("leave: load categories: %w", err)
		}
		for _, c := range cats {
			n.category[c.ID] = c.Name
		}
	}
	return n, nil
}

// EntitlementView is an entitlement with the names and field aliases the UI shows.
type EntitlementView struct {
	*ent.LeaveEntitlement
	EmployeeName      string `json:"employee_name"`
	EmployeeNumber    string `json:"employee_number"`
	LeaveCategoryName string `json:"leave_category_name"`
	Days              string `json:"days"`
}

// ListEntitlementsEnriched returns entitlements with employee and leave type names.
func (s *Service) ListEntitlementsEnriched(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, year int) ([]EntitlementView, error) {
	rows, err := s.ListEntitlements(ctx, tenantID, employeeID, year)
	if err != nil {
		return nil, err
	}
	empIDs := make([]uuid.UUID, 0, len(rows))
	catIDs := make([]uuid.UUID, 0, len(rows))
	for _, r := range rows {
		empIDs = append(empIDs, r.EmployeeID)
		catIDs = append(catIDs, r.CategoryID)
	}
	n, err := s.lookupNames(ctx, tenantID, empIDs, catIDs)
	if err != nil {
		return nil, err
	}
	out := make([]EntitlementView, len(rows))
	for i, r := range rows {
		out[i] = EntitlementView{LeaveEntitlement: r, EmployeeName: n.employee[r.EmployeeID],
			EmployeeNumber: n.employeeNumber[r.EmployeeID], LeaveCategoryName: n.category[r.CategoryID],
			Days: r.DaysEntitled.String()}
	}
	return out, nil
}

// RequestView is a leave request with the employee and leave type names and day count.
type RequestView struct {
	*ent.LeaveRequest
	EmployeeName      string `json:"employee_name"`
	EmployeeNumber    string `json:"employee_number"`
	LeaveCategoryName string `json:"leave_category_name"`
	Days              string `json:"days"`
	// The half-day flags are always sent (ent leaves a false one out).
	StartHalfDay bool `json:"start_half_day"`
	EndHalfDay   bool `json:"end_half_day"`
}

// RequestViews adds names to a page of leave requests.
func (s *Service) RequestViews(ctx context.Context, tenantID uuid.UUID, rows []*ent.LeaveRequest) ([]RequestView, error) {
	empIDs := make([]uuid.UUID, 0, len(rows))
	catIDs := make([]uuid.UUID, 0, len(rows))
	for _, r := range rows {
		empIDs = append(empIDs, r.EmployeeID)
		catIDs = append(catIDs, r.CategoryID)
	}
	n, err := s.lookupNames(ctx, tenantID, empIDs, catIDs)
	if err != nil {
		return nil, err
	}
	out := make([]RequestView, len(rows))
	for i, r := range rows {
		out[i] = RequestView{LeaveRequest: r, EmployeeName: n.employee[r.EmployeeID],
			EmployeeNumber: n.employeeNumber[r.EmployeeID], LeaveCategoryName: n.category[r.CategoryID],
			Days: r.DaysRequested.String(), StartHalfDay: r.StartHalfDay, EndHalfDay: r.EndHalfDay}
	}
	return out, nil
}

// LogView is a leave log line with the name of the employee whose request it belongs to.
type LogView struct {
	*ent.LeaveLog
	EmployeeName string `json:"employee_name"`
}

// LogViews resolves each log's employee through its leave request, one query per kind.
func (s *Service) LogViews(ctx context.Context, tenantID uuid.UUID, rows []*ent.LeaveLog) ([]LogView, error) {
	reqIDs := make([]uuid.UUID, 0, len(rows))
	for _, r := range rows {
		reqIDs = append(reqIDs, r.LeaveRequestID)
	}
	empOf := map[uuid.UUID]uuid.UUID{}
	if len(reqIDs) > 0 {
		reqs, err := s.orm.LeaveRequest.Query().Where(leaverequest.TenantID(tenantID), leaverequest.IDIn(reqIDs...)).
			Select(leaverequest.FieldID, leaverequest.FieldEmployeeID).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("leave: load requests: %w", err)
		}
		for _, q := range reqs {
			empOf[q.ID] = q.EmployeeID
		}
	}
	empIDs := make([]uuid.UUID, 0, len(empOf))
	for _, e := range empOf {
		empIDs = append(empIDs, e)
	}
	n, err := s.lookupNames(ctx, tenantID, empIDs, nil)
	if err != nil {
		return nil, err
	}
	out := make([]LogView, len(rows))
	for i, r := range rows {
		out[i] = LogView{LeaveLog: r, EmployeeName: n.employee[empOf[r.LeaveRequestID]]}
	}
	return out, nil
}

// ErrDuplicateCategory is returned when a tenant already has a leave type with the same name.
var ErrDuplicateCategory = fmt.Errorf("a leave type with this name already exists")

// ensureUniqueCategoryName refuses a leave type name the tenant already uses, ignoring case and
// surrounding spaces ("Annual leave" and "Annual Leave" are the same type). except skips the row
// being renamed.
func (s *Service) ensureUniqueCategoryName(ctx context.Context, tenantID uuid.UUID, name string, except *uuid.UUID) error {
	q := s.orm.LeaveCategory.Query().Where(leavecategory.TenantID(tenantID),
		leavecategory.NameEqualFold(strings.TrimSpace(name)))
	if except != nil {
		q = q.Where(leavecategory.IDNEQ(*except))
	}
	exists, err := q.Exist(ctx)
	if err != nil {
		return fmt.Errorf("leave: check category name: %w", err)
	}
	if exists {
		return ErrDuplicateCategory
	}
	return nil
}
