package employees

import (
	"context"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
)

// maxLookup caps one lookup page; a picker shows the first matches and narrows as the user types.
const maxLookup = 50

// LookupRow is the little a picker in another service needs: who the employee is, never their pay,
// ID or bank details. Callers keep the id and name; the record stays in erp.
type LookupRow struct {
	ID             uuid.UUID `json:"id"`
	EmployeeNumber string    `json:"employee_number,omitempty"`
	Name           string    `json:"name"`
	Email          string    `json:"email,omitempty"`
}

// Lookup returns active employees (not deleted, not terminated) whose name, staff number or email
// contains q, by name, at most 50. An empty q lists the first employees by name.
func (s *Service) Lookup(ctx context.Context, tenantID uuid.UUID, q string, limit int) ([]LookupRow, error) {
	if limit <= 0 || limit > maxLookup {
		limit = maxLookup
	}
	query := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.Deleted(false), employee.Terminated(false))
	if q = strings.TrimSpace(q); q != "" {
		query = query.Where(employee.Or(
			employee.FirstNameContainsFold(q), employee.LastNameContainsFold(q),
			employee.EmployeeNumberContainsFold(q), employee.EmailContainsFold(q),
		))
	}
	rows, err := query.Order(ent.Asc(employee.FieldFirstName), ent.Asc(employee.FieldLastName)).
		Select(employee.FieldID, employee.FieldEmployeeNumber, employee.FieldFirstName, employee.FieldLastName, employee.FieldEmail).
		Limit(limit).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("employees: lookup: %w", err)
	}
	out := make([]LookupRow, 0, len(rows))
	for _, e := range rows {
		row := LookupRow{ID: e.ID, Name: strings.TrimSpace(e.FirstName + " " + e.LastName), Email: e.Email}
		if e.EmployeeNumber != nil {
			row.EmployeeNumber = *e.EmployeeNumber
		}
		if row.Name == "" {
			row.Name = row.EmployeeNumber
		}
		out = append(out, row)
	}
	return out, nil
}
