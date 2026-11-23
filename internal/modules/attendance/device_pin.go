package attendance

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
)

// ErrPINTaken is returned when another employee of the tenant already has the PIN.
var ErrPINTaken = errors.New("attendance: device PIN already belongs to another employee")

// pinPattern is what ZKTeco terminals accept as a user PIN.
var pinPattern = regexp.MustCompile(`^[0-9A-Za-z]{1,24}$`)

// backfillPunchesSQL attaches a PIN's unmatched device punches to the employee who now holds it.
const backfillPunchesSQL = `
UPDATE attendance_punches SET employee_id = $3
WHERE tenant_id = $1 AND device_pin = $2 AND employee_id IS NULL AND source = 'device'`

// SetDevicePIN sets (or with an empty pin clears) the employee's device PIN. Device punches
// already received under the PIN with no employee are attached to them and processed.
func (s *Service) SetDevicePIN(ctx context.Context, tenantID, empID uuid.UUID, pin string) (*ent.Employee, error) {
	emp, err := s.loadEmployee(ctx, tenantID, empID)
	if err != nil {
		return nil, err
	}
	pin = strings.TrimSpace(pin)
	if pin == "" {
		return emp.Update().ClearDevicePin().Save(ctx)
	}
	if !pinPattern.MatchString(pin) {
		return nil, errors.New("pin must be 1 to 24 letters or digits")
	}
	row, err := emp.Update().SetDevicePin(pin).Save(ctx)
	if ent.IsConstraintError(err) {
		return nil, ErrPINTaken
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: set device pin: %w", err)
	}
	res, err := s.orm.ExecContext(ctx, backfillPunchesSQL, tenantID, pin, empID)
	if err != nil {
		return row, fmt.Errorf("attendance: attach unmatched punches: %w", err)
	}
	if n, _ := res.RowsAffected(); n > 0 {
		s.KickProcessor(tenantID)
	}
	return row, nil
}

// deviceUsers is the tenant's active employees with a PIN who belong on the device: those of
// its outlet and those without an outlet (all of them when the device has no outlet).
func (s *Service) deviceUsers(ctx context.Context, tenantID uuid.UUID, dev *ent.AttendanceDevice) ([]DeviceUser, error) {
	q := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.DevicePinNotNil(),
		employee.Deleted(false), employee.Terminated(false))
	if dev.OutletID != nil {
		q = q.Where(employee.Or(employee.OutletIDIsNil(), employee.OutletID(*dev.OutletID)))
	}
	rows, err := q.Order(ent.Asc(employee.FieldDevicePin)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: device users: %w", err)
	}
	out := make([]DeviceUser, 0, len(rows))
	for _, e := range rows {
		out = append(out, DeviceUser{PIN: *e.DevicePin, Name: strings.TrimSpace(e.FirstName + " " + e.LastName)})
	}
	return out, nil
}
