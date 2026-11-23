package attendance

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalrequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendanceregularisation"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
)

// RegularisationInput is a correction request: the day and the times it should have.
type RegularisationInput struct {
	EmployeeID  uuid.UUID
	Date        time.Time
	CheckIn     string // "HH:MM" company time, optional
	CheckOut    string // "HH:MM" company time, optional
	Reason      string
	RequestedBy *uuid.UUID
}

// TimesPair is a check-in and check-out shown before a correction.
type TimesPair struct {
	CheckIn  *time.Time `json:"check_in"`
	CheckOut *time.Time `json:"check_out"`
}

// RegularisationView is a regularisation row for lists.
type RegularisationView struct {
	*ent.AttendanceRegularisation
	EmployeeName string    `json:"employee_name"`
	Before       TimesPair `json:"before"`
}

// CreateRegularisation records a correction request and submits it for approval. The record's
// current times are kept as "before" so the reviewer sees the change.
func (s *Service) CreateRegularisation(ctx context.Context, tenantID uuid.UUID, in RegularisationInput) (*RegularisationView, error) {
	if s.approvals == nil {
		return nil, ErrApprovalsUnavailable
	}
	in.Reason = strings.TrimSpace(in.Reason)
	if in.Reason == "" {
		return nil, errors.New("reason is required")
	}
	if in.CheckIn == "" && in.CheckOut == "" {
		return nil, errors.New("give check_in, check_out or both")
	}
	date := dateOnly(in.Date)
	if in.Date.IsZero() || date.After(dateOnly(time.Now()).AddDate(0, 0, 1)) {
		return nil, errors.New("date must be today or earlier")
	}
	emp, err := s.loadEmployee(ctx, tenantID, in.EmployeeID)
	if err != nil {
		return nil, err
	}
	zones, err := s.loadZones(ctx, tenantID)
	if err != nil {
		return nil, fmt.Errorf("attendance: zones: %w", err)
	}
	checkIn, checkOut, err := clockTimes(date, in.CheckIn, in.CheckOut, zones.For())
	if err != nil {
		return nil, err
	}
	rec, err := s.orm.AttendanceRecord.Query().Where(attendancerecord.TenantID(tenantID),
		attendancerecord.EmployeeID(emp.ID), attendancerecord.Date(date)).Only(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return nil, fmt.Errorf("attendance: record lookup: %w", err)
	}
	before := map[string]any{"check_in": nil, "check_out": nil, "status": nil}
	var recID *uuid.UUID
	if rec != nil {
		before = timesMap(rec.CheckIn, rec.CheckOut, string(rec.Status))
		recID = &rec.ID
	}
	row, err := s.orm.AttendanceRegularisation.Create().SetTenantID(tenantID).SetEmployeeID(emp.ID).
		SetDate(date).SetNillableCheckIn(checkIn).SetNillableCheckOut(checkOut).SetReason(in.Reason).
		SetNillableRecordID(recID).SetBefore(before).SetNillableRequestedBy(in.RequestedBy).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create regularisation: %w", err)
	}
	req, err := s.approvals.SubmitWithFallback(ctx, tenantID, approvals.SubmitInput{
		Module: ModuleRegularisation, ObjectID: row.ID,
		ObjectReference:     fmt.Sprintf("Attendance correction %s %s", employeeName(emp), date.Format("2006-01-02")),
		RequesterEmployeeID: &emp.ID, SubmittedBy: in.RequestedBy,
	}, fallbackApproverRole)
	if err != nil {
		return nil, fmt.Errorf("attendance: submit regularisation: %w", err)
	}
	if row, err = row.Update().SetApprovalRequestID(req.ID).Save(ctx); err != nil {
		return nil, fmt.Errorf("attendance: link approval: %w", err)
	}
	return &RegularisationView{AttendanceRegularisation: row, EmployeeName: employeeName(emp), Before: beforePair(row.Before)}, nil
}

func employeeName(e *ent.Employee) string {
	return strings.TrimSpace(e.FirstName + " " + e.LastName)
}

// beforePair reads the before snapshot back into times.
func beforePair(m map[string]any) TimesPair {
	var p TimesPair
	for k, dst := range map[string]**time.Time{"check_in": &p.CheckIn, "check_out": &p.CheckOut} {
		if v, ok := m[k].(string); ok {
			if t, err := time.Parse(time.RFC3339, v); err == nil {
				*dst = &t
			}
		}
	}
	return p
}

// CorrectionFilter narrows regularisation and overtime request lists.
type CorrectionFilter struct {
	EmployeeID *uuid.UUID
	Status     string
	From, To   *time.Time
}

// ListRegularisations returns one page of regularisations, newest first, over a bounded range.
func (s *Service) ListRegularisations(ctx context.Context, tenantID uuid.UUID, f CorrectionFilter, limit, offset int) ([]RegularisationView, int, error) {
	lo, hi := boundRange(f.From, f.To, time.Now())
	q := s.orm.AttendanceRegularisation.Query().Where(attendanceregularisation.TenantID(tenantID),
		attendanceregularisation.DateGTE(lo), attendanceregularisation.DateLT(hi.AddDate(0, 0, 1)))
	if f.EmployeeID != nil {
		q = q.Where(attendanceregularisation.EmployeeID(*f.EmployeeID))
	}
	if f.Status != "" {
		q = q.Where(attendanceregularisation.StatusEQ(attendanceregularisation.Status(f.Status)))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("attendance: count regularisations: %w", err)
	}
	rows, err := q.Order(ent.Desc(attendanceregularisation.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("attendance: list regularisations: %w", err)
	}
	ids := make([]uuid.UUID, len(rows))
	for i, r := range rows {
		ids[i] = r.EmployeeID
	}
	names := s.employeeNames(ctx, tenantID, ids)
	out := make([]RegularisationView, len(rows))
	for i, r := range rows {
		out[i] = RegularisationView{AttendanceRegularisation: r, EmployeeName: names[r.EmployeeID], Before: beforePair(r.Before)}
	}
	return out, total, nil
}

// applyRegularisationDecision is the approvals hook. Approved: the record takes the requested
// times, is re-evaluated, and keeps the before and after values in metadata corrections[].
// Rejected or cancelled: only the request status changes. A request no longer pending was
// applied already, so a repeated call changes nothing.
func (s *Service) applyRegularisationDecision(ctx context.Context, tenantID uuid.UUID, req *ent.ApprovalRequest) error {
	reg, err := s.orm.AttendanceRegularisation.Query().Where(attendanceregularisation.TenantID(tenantID),
		attendanceregularisation.ID(req.ObjectID)).Only(ctx)
	if err != nil {
		return fmt.Errorf("load regularisation: %w", err)
	}
	if reg.Status != attendanceregularisation.StatusPending {
		return nil
	}
	now := time.Now().UTC()
	if req.Status != approvalrequest.StatusApproved {
		st := attendanceregularisation.StatusRejected
		if req.Status == approvalrequest.StatusCancelled {
			st = attendanceregularisation.StatusCancelled
		}
		return reg.Update().SetStatus(st).SetDecidedAt(now).Exec(ctx)
	}
	emp, err := s.loadEmployee(ctx, tenantID, reg.EmployeeID)
	if err != nil {
		return err
	}
	rec, err := s.setDayTimes(ctx, tenantID, emp, reg.Date, reg.CheckIn, reg.CheckOut,
		func(meta map[string]any, res evalResult, in, out *time.Time) {
			appendCorrection(meta, map[string]any{
				"regularisation_id":   reg.ID.String(),
				"approval_request_id": req.ID.String(),
				"reason":              reg.Reason,
				"before":              reg.Before,
				"after":               timesMap(in, out, res.Status),
				"applied_at":          now.Format(time.RFC3339),
			})
		})
	if err != nil {
		return err
	}
	if err := reg.Update().SetStatus(attendanceregularisation.StatusApproved).SetDecidedAt(now).
		SetRecordID(rec.ID).Exec(ctx); err != nil {
		return fmt.Errorf("mark regularisation approved: %w", err)
	}
	s.publish(ctx, tenantID, rec.ID, "attendance.record.corrected", map[string]any{
		"record_id": rec.ID.String(), "employee_id": rec.EmployeeID.String(),
		"date": dateOnly(rec.Date).Format("2006-01-02"), "regularisation_id": reg.ID.String(),
		"approval_request_id": req.ID.String(), "before": reg.Before,
	})
	return nil
}
