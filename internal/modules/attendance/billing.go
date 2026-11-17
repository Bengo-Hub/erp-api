package attendance

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// Billing of project time. projects-api reserves the approved, billable entries of a period under a
// billing_ref (one invoice run), creates the invoice in treasury, then confirms the ref with the
// invoice id, or releases it when the invoice could not be created. Both keys live in the entry's
// metadata, so an entry is billed at most once and a failed run can be retried with the same ref.
// When treasury voids or deletes the invoice, a release with include_confirmed frees the entries for
// a new run.

// MaxBillingSpanDays caps the period one reservation may cover.
const MaxBillingSpanDays = 366

var (
	// ErrBillingPeriod is returned for a period that is reversed or longer than MaxBillingSpanDays.
	ErrBillingPeriod = errors.New("attendance: from must not be after to, and the period may span at most 366 days")
)

// BillingEntry is one reserved entry as projects-api turns it into an invoice line.
type BillingEntry struct {
	ID           uuid.UUID       `json:"id"`
	Date         string          `json:"date"`
	TaskID       *uuid.UUID      `json:"task_id"`
	EmployeeID   uuid.UUID       `json:"employee_id"`
	EmployeeName string          `json:"employee_name"`
	Hours        decimal.Decimal `json:"hours"`
	Description  string          `json:"description"`
}

// BillingReservation is every entry carrying a billing_ref, and the invoice they were confirmed on.
type BillingReservation struct {
	Data            []BillingEntry `json:"data"`
	BilledInvoiceID *string        `json:"billed_invoice_id"`
}

// dayRange turns an inclusive from/to date pair into the half-open [from, to+1 day) bound the
// queries use, so an entry stored at any time on the last day still counts.
func dayRange(from, to time.Time) (time.Time, time.Time) {
	return from, to.AddDate(0, 0, 1)
}

const reserveEntriesSQL = `UPDATE timesheet_entries e
SET metadata = COALESCE(e.metadata, '{}'::jsonb) || jsonb_build_object('billing_ref', $5::text)
FROM timesheets t
WHERE e.tenant_id = $1 AND e.project_id = $2 AND e.billable
  AND e.date >= $3 AND e.date < $4
  AND e.metadata->>'billing_ref' IS NULL
  AND t.id = e.timesheet_id AND t.tenant_id = $1 AND t.status = 'approved'`

const reservedEntriesSQL = `SELECT e.id, e.date, e.task_id, t.employee_id,
  TRIM(COALESCE(emp.first_name, '') || ' ' || COALESCE(emp.last_name, '')),
  (COALESCE(e.regular_hours, 0) + COALESCE(e.overtime_hours, 0))::text,
  COALESCE(e.task_description, ''), e.metadata->>'billed_invoice_id'
FROM timesheet_entries e
JOIN timesheets t ON t.id = e.timesheet_id
LEFT JOIN employees emp ON emp.id = t.employee_id
WHERE e.tenant_id = $1 AND e.project_id = $2 AND e.metadata->>'billing_ref' = $3
ORDER BY e.date, e.id`

// ReserveBillableEntries marks the approved, billable entries of a project in [from, to] that no
// run has reserved yet with billingRef, and returns every entry carrying billingRef, including the
// ones an earlier attempt with the same ref reserved. The reservation is one UPDATE: a concurrent
// call waits on the row locks and then skips rows that already carry a ref, so no entry is reserved
// twice.
func (s *Service) ReserveBillableEntries(ctx context.Context, tenantID, projectID uuid.UUID, from, to time.Time, billingRef uuid.UUID) (*BillingReservation, error) {
	if to.Before(from) || to.Sub(from) > MaxBillingSpanDays*24*time.Hour {
		return nil, ErrBillingPeriod
	}
	lo, hi := dayRange(from, to)
	var out *BillingReservation
	err := s.inTx(ctx, func(tx *ent.Tx) error {
		if _, err := tx.ExecContext(ctx, reserveEntriesSQL, tenantID, projectID, lo, hi, billingRef.String()); err != nil {
			return fmt.Errorf("attendance: reserve entries: %w", err)
		}
		rows, err := tx.QueryContext(ctx, reservedEntriesSQL, tenantID, projectID, billingRef.String())
		if err != nil {
			return fmt.Errorf("attendance: load reserved entries: %w", err)
		}
		defer rows.Close()
		out = &BillingReservation{Data: []BillingEntry{}}
		for rows.Next() {
			var (
				e      BillingEntry
				date   time.Time
				task   uuid.NullUUID
				hours  string
				billed sql.NullString
			)
			if err := rows.Scan(&e.ID, &date, &task, &e.EmployeeID, &e.EmployeeName, &hours, &e.Description, &billed); err != nil {
				return fmt.Errorf("attendance: scan reserved entry: %w", err)
			}
			e.Date = date.UTC().Format(time.DateOnly)
			if task.Valid {
				id := task.UUID
				e.TaskID = &id
			}
			if e.Hours, err = decimal.NewFromString(hours); err != nil {
				return fmt.Errorf("attendance: entry hours: %w", err)
			}
			if billed.Valid && out.BilledInvoiceID == nil {
				v := billed.String
				out.BilledInvoiceID = &v
			}
			out.Data = append(out.Data, e)
		}
		return rows.Err()
	})
	if err != nil {
		return nil, err
	}
	return out, nil
}

// ConfirmBilling records invoiceID on every entry carrying billingRef, replacing any invoice id an
// earlier confirmation left (a draft deleted in treasury leaves entries pointing at a dead invoice,
// and the next invoice for the same ref takes them over). It returns how many entries carry the ref,
// so a repeated call returns the same count.
func (s *Service) ConfirmBilling(ctx context.Context, tenantID, billingRef, invoiceID uuid.UUID) (int, error) {
	res, err := s.orm.ExecContext(ctx, `UPDATE timesheet_entries
SET metadata = metadata || jsonb_build_object('billed_invoice_id', $3::text)
WHERE tenant_id = $1 AND metadata->>'billing_ref' = $2`,
		tenantID, billingRef.String(), invoiceID.String())
	if err != nil {
		return 0, fmt.Errorf("attendance: confirm billing: %w", err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("attendance: confirm billing: %w", err)
	}
	return int(n), nil
}

// ReleaseBilling clears billingRef from the entries that were not confirmed on an invoice, so a
// later run can bill them, and returns how many it freed. With includeConfirmed it also frees the
// confirmed ones, clearing billed_invoice_id too; projects-api asks for that only after treasury
// shows the invoice void or cancelled.
func (s *Service) ReleaseBilling(ctx context.Context, tenantID, billingRef uuid.UUID, includeConfirmed bool) (int, error) {
	res, err := s.orm.ExecContext(ctx, `UPDATE timesheet_entries
SET metadata = metadata - 'billing_ref' - 'billed_invoice_id'
WHERE tenant_id = $1 AND metadata->>'billing_ref' = $2 AND ($3::boolean OR metadata->>'billed_invoice_id' IS NULL)`,
		tenantID, billingRef.String(), includeConfirmed)
	if err != nil {
		return 0, fmt.Errorf("attendance: release billing: %w", err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("attendance: release billing: %w", err)
	}
	return int(n), nil
}

// inTx runs fn in one transaction, rolling back on error.
func (s *Service) inTx(ctx context.Context, fn func(tx *ent.Tx) error) error {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return fmt.Errorf("attendance: begin: %w", err)
	}
	if err := fn(tx); err != nil {
		_ = tx.Rollback()
		return err
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("attendance: commit: %w", err)
	}
	return nil
}
