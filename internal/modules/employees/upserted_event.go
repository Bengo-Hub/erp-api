package employees

import (
	"context"
	"strings"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/hook"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
)

// EventEmployeeUpserted is published (subject erp.employee.upserted) whenever an employee is
// created or their name, staff number, login link, exit or deletion changes. POS staff credit
// keeps its employee names and numbers from it.
const EventEmployeeUpserted = "employee.upserted"

// sharedFields are the employee fields other services keep a copy of.
var sharedFields = []string{
	employee.FieldFirstName, employee.FieldLastName, employee.FieldEmployeeNumber, employee.FieldUserID,
	employee.FieldEmail, employee.FieldTerminated, employee.FieldDeleted,
}

// UpsertedEventHook writes erp.employee.upserted to the outbox in the same transaction as every
// single-row employee create or update that touches a shared field, so the event exists exactly
// when the change commits. Register it once on the client (orm.Employee.Use).
func UpsertedEventHook(source string) ent.Hook {
	return func(next ent.Mutator) ent.Mutator {
		return hook.EmployeeFunc(func(ctx context.Context, m *ent.EmployeeMutation) (ent.Value, error) {
			v, err := next.Mutate(ctx, m)
			if err != nil || !m.Op().Is(ent.OpCreate|ent.OpUpdateOne) {
				return v, err
			}
			if m.Op().Is(ent.OpUpdateOne) && !touchesShared(m) {
				return v, nil
			}
			e, ok := v.(*ent.Employee)
			if !ok || e == nil {
				return v, nil
			}
			if perr := events.NewPublisher(m.Client(), source).Publish(ctx, e.TenantID, e.ID, EventEmployeeUpserted, upsertedPayload(e)); perr != nil {
				return nil, perr
			}
			return v, nil
		})
	}
}

func touchesShared(m *ent.EmployeeMutation) bool {
	for _, f := range m.Fields() {
		for _, s := range sharedFields {
			if f == s {
				return true
			}
		}
	}
	for _, f := range m.ClearedFields() {
		for _, s := range sharedFields {
			if f == s {
				return true
			}
		}
	}
	return false
}

func upsertedPayload(e *ent.Employee) map[string]any {
	p := map[string]any{
		"employee_id": e.ID.String(),
		"tenant_id":   e.TenantID.String(),
		"name":        strings.TrimSpace(e.FirstName + " " + e.LastName),
		"email":       e.Email,
		"terminated":  e.Terminated,
		"deleted":     e.Deleted,
	}
	if e.EmployeeNumber != nil {
		p["employee_number"] = *e.EmployeeNumber
	}
	if e.UserID != nil {
		// The ERP user shadow's id is the auth-api user id.
		p["auth_user_id"] = e.UserID.String()
	}
	return p
}
