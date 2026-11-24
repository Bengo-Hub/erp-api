package attendance

import (
	"context"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancedevice"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
)

// API views: the wire shapes erp-ui reads for work sites, punches and access events. Names
// are resolved in one query per kind for the whole page, never per row.

// LatLng is a coordinate pair on the wire.
type LatLng struct {
	Lat float64 `json:"lat"`
	Lng float64 `json:"lng"`
}

// WorkSiteView is a work site with its centre as {lat, lng}.
type WorkSiteView struct {
	ID       uuid.UUID     `json:"id"`
	OutletID *uuid.UUID    `json:"outlet_id"`
	Name     string        `json:"name"`
	Center   LatLng        `json:"center"`
	RadiusM  float64       `json:"radius_m"`
	Ring     [][]float64   `json:"ring"`
	Holes    [][][]float64 `json:"holes,omitempty"`
	Active   bool          `json:"active"`
}

// NewWorkSiteView maps a stored site to its wire shape; an empty ring is sent as null.
func NewWorkSiteView(w *ent.WorkSite) WorkSiteView {
	v := WorkSiteView{ID: w.ID, OutletID: w.OutletID, Name: w.Name,
		Center: LatLng{Lat: w.CenterLat, Lng: w.CenterLng}, RadiusM: w.RadiusM, Holes: w.Holes, Active: w.Active}
	if len(w.Ring) >= 3 {
		v.Ring = w.Ring
	}
	return v
}

// WorkSiteViews maps a list of sites.
func WorkSiteViews(rows []*ent.WorkSite) []WorkSiteView {
	out := make([]WorkSiteView, len(rows))
	for i, w := range rows {
		out[i] = NewWorkSiteView(w)
	}
	return out
}

// RecordView is an attendance record with the employee's name and number and the total hours
// the records table shows.
type RecordView struct {
	*ent.AttendanceRecord
	EmployeeName   string `json:"employee_name"`
	EmployeeNumber string `json:"employee_number"`
	HoursWorked    string `json:"hours_worked"`
}

// RecordViews adds names and total hours to a page of records.
func (s *Service) RecordViews(ctx context.Context, tenantID uuid.UUID, rows []*ent.AttendanceRecord) []RecordView {
	ids := make([]*uuid.UUID, 0, len(rows))
	for _, r := range rows {
		id := r.EmployeeID
		ids = append(ids, &id)
	}
	names, numbers := s.employeeLabels(ctx, tenantID, uniq(ids...))
	out := make([]RecordView, len(rows))
	for i, r := range rows {
		v := RecordView{AttendanceRecord: r, EmployeeName: names[r.EmployeeID], EmployeeNumber: numbers[r.EmployeeID]}
		if r.CheckOut != nil {
			v.HoursWorked = r.RegularHours.Add(r.OvertimeHours).StringFixed(2)
		}
		out[i] = v
	}
	return out
}

// PunchView is a raw punch with its device and employee names; record_id is null while the
// punch is not yet (or cannot be) matched to an attendance record.
type PunchView struct {
	*ent.AttendancePunch
	DeviceName   string     `json:"device_name"`
	EmployeeName string     `json:"employee_name"`
	RecordID     *uuid.UUID `json:"record_id"`
}

// AccessEventView is a door event with its device and employee names and a readable reason.
type AccessEventView struct {
	*ent.AccessEvent
	DeviceName   string `json:"device_name"`
	EmployeeName string `json:"employee_name"`
	Reason       string `json:"reason"`
}

// employeeNames resolves "First Last" for a set of employee ids in one query.
func (s *Service) employeeNames(ctx context.Context, tenantID uuid.UUID, ids []uuid.UUID) map[uuid.UUID]string {
	names, _ := s.employeeLabels(ctx, tenantID, ids)
	return names
}

// employeeLabels resolves "First Last" and the staff number for a set of employee ids in one query.
func (s *Service) employeeLabels(ctx context.Context, tenantID uuid.UUID, ids []uuid.UUID) (names, numbers map[uuid.UUID]string) {
	names, numbers = map[uuid.UUID]string{}, map[uuid.UUID]string{}
	if len(ids) == 0 {
		return
	}
	rows, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(ids...)).
		Select(employee.FieldID, employee.FieldFirstName, employee.FieldLastName, employee.FieldEmployeeNumber).All(ctx)
	if err != nil {
		return
	}
	for _, e := range rows {
		names[e.ID] = strings.TrimSpace(e.FirstName + " " + e.LastName)
		if e.EmployeeNumber != nil {
			numbers[e.ID] = *e.EmployeeNumber
		}
	}
	return
}

// deviceNames resolves device names for a set of device ids in one query.
func (s *Service) deviceNames(ctx context.Context, tenantID uuid.UUID, ids []uuid.UUID) map[uuid.UUID]string {
	out := map[uuid.UUID]string{}
	if len(ids) == 0 {
		return out
	}
	rows, err := s.orm.AttendanceDevice.Query().
		Where(attendancedevice.TenantID(tenantID), attendancedevice.IDIn(ids...)).
		Select(attendancedevice.FieldID, attendancedevice.FieldName).All(ctx)
	if err != nil {
		return out
	}
	for _, d := range rows {
		out[d.ID] = d.Name
	}
	return out
}

// uniq collects distinct non-nil ids.
func uniq(ids ...*uuid.UUID) []uuid.UUID {
	seen := map[uuid.UUID]bool{}
	out := []uuid.UUID{}
	for _, id := range ids {
		if id != nil && !seen[*id] {
			seen[*id] = true
			out = append(out, *id)
		}
	}
	return out
}

// PunchViews adds names to a page of punches.
func (s *Service) PunchViews(ctx context.Context, tenantID uuid.UUID, rows []*ent.AttendancePunch) []PunchView {
	devIDs, empIDs := make([]*uuid.UUID, 0, len(rows)), make([]*uuid.UUID, 0, len(rows))
	for _, p := range rows {
		devIDs, empIDs = append(devIDs, p.DeviceID), append(empIDs, p.EmployeeID)
	}
	devs, emps := s.deviceNames(ctx, tenantID, uniq(devIDs...)), s.employeeNames(ctx, tenantID, uniq(empIDs...))
	out := make([]PunchView, len(rows))
	for i, p := range rows {
		v := PunchView{AttendancePunch: p, RecordID: p.AttendanceRecordID}
		if p.DeviceID != nil {
			v.DeviceName = devs[*p.DeviceID]
		}
		if p.EmployeeID != nil {
			v.EmployeeName = emps[*p.EmployeeID]
		}
		out[i] = v
	}
	return out
}

// accessReason turns the event into a short label for the access log.
func accessReason(e *ent.AccessEvent) string {
	switch {
	case e.Result == "granted":
		return "Access granted"
	case e.EmployeeID == nil && e.DevicePin == "":
		return "Unknown card or face"
	case e.EmployeeID == nil:
		return "User not linked to an employee"
	default:
		return "Access denied by the device"
	}
}

// AccessEventViews adds names and reasons to a page of access events.
func (s *Service) AccessEventViews(ctx context.Context, tenantID uuid.UUID, rows []*ent.AccessEvent) []AccessEventView {
	devIDs, empIDs := make([]*uuid.UUID, 0, len(rows)), make([]*uuid.UUID, 0, len(rows))
	for _, e := range rows {
		id := e.DeviceID
		devIDs, empIDs = append(devIDs, &id), append(empIDs, e.EmployeeID)
	}
	devs, emps := s.deviceNames(ctx, tenantID, uniq(devIDs...)), s.employeeNames(ctx, tenantID, uniq(empIDs...))
	out := make([]AccessEventView, len(rows))
	for i, e := range rows {
		v := AccessEventView{AccessEvent: e, DeviceName: devs[e.DeviceID], Reason: accessReason(e)}
		if e.EmployeeID != nil {
			v.EmployeeName = emps[*e.EmployeeID]
		}
		out[i] = v
	}
	return out
}
