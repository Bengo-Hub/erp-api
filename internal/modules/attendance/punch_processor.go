package attendance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancepunch"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
)

// processBatchSize bounds the pending punches read per round.
const processBatchSize = 2000

// markPunchesSQL links processed punches to their records in one statement.
const markPunchesSQL = `
UPDATE attendance_punches p
SET processed = true, attendance_record_id = v.rid
FROM unnest($1::uuid[], $2::uuid[]) AS v(pid, rid)
WHERE p.id = v.pid`

// ProcessPendingPunches pairs every matched, unprocessed punch into attendance records, for
// one tenant or (uuid.Nil) all tenants. Punches whose PIN matches no employee stay pending
// until a PIN is assigned. Returns the number of records written.
func (s *Service) ProcessPendingPunches(ctx context.Context, tenantID uuid.UUID) (int, error) {
	total := 0
	for round := 0; round < 50; round++ {
		q := s.orm.AttendancePunch.Query().Where(
			attendancepunch.Processed(false), attendancepunch.EmployeeIDNotNil())
		if tenantID != uuid.Nil {
			q = q.Where(attendancepunch.TenantID(tenantID))
		}
		pending, err := q.Order(ent.Asc(attendancepunch.FieldPunchedAt)).Limit(processBatchSize).All(ctx)
		if err != nil {
			return total, fmt.Errorf("attendance: pending punches: %w", err)
		}
		if len(pending) == 0 {
			return total, nil
		}
		byTenant := map[uuid.UUID][]*ent.AttendancePunch{}
		for _, p := range pending {
			byTenant[p.TenantID] = append(byTenant[p.TenantID], p)
		}
		for tid, ps := range byTenant {
			n, err := s.processTenantPunches(ctx, tid, ps)
			if err != nil {
				return total, err
			}
			total += n
		}
		if len(pending) < processBatchSize {
			return total, nil
		}
	}
	return total, nil
}

// processTenantPunches recomputes the records of every employee day touched by pending, from
// all punches of those days (already processed ones included), in a fixed number of queries.
func (s *Service) processTenantPunches(ctx context.Context, tenantID uuid.UUID, pending []*ent.AttendancePunch) (int, error) {
	st, err := s.GetSettings(ctx, tenantID)
	if err != nil {
		return 0, err
	}
	zones, err := s.loadZones(ctx, tenantID)
	if err != nil {
		return 0, fmt.Errorf("attendance: zones: %w", err)
	}
	empSet := map[uuid.UUID]bool{}
	lo, hi := pending[0].PunchedAt, pending[0].PunchedAt
	for _, p := range pending {
		empSet[*p.EmployeeID] = true
		if p.PunchedAt.Before(lo) {
			lo = p.PunchedAt
		}
		if p.PunchedAt.After(hi) {
			hi = p.PunchedAt
		}
	}
	empIDs := make([]uuid.UUID, 0, len(empSet))
	for id := range empSet {
		empIDs = append(empIDs, id)
	}
	emps, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(empIDs...)).
		Select(employee.FieldID, employee.FieldOutletID, employee.FieldDevicePin).All(ctx)
	if err != nil {
		return 0, fmt.Errorf("attendance: punch employees: %w", err)
	}
	outletOf := map[uuid.UUID]*uuid.UUID{}
	for _, e := range emps {
		outletOf[e.ID] = e.OutletID
	}

	// Every punch of the touched days: a day can start the evening before (night shift).
	all, err := s.orm.AttendancePunch.Query().Where(
		attendancepunch.TenantID(tenantID), attendancepunch.EmployeeIDIn(empIDs...),
		attendancepunch.PunchedAtGTE(lo.Add(-36*time.Hour)), attendancepunch.PunchedAtLTE(hi.Add(36*time.Hour)),
	).All(ctx)
	if err != nil {
		return 0, fmt.Errorf("attendance: day punches: %w", err)
	}
	keySet := map[empDay]bool{}
	for _, p := range all {
		d := localDate(p.PunchedAt, zones.For(outletOf[*p.EmployeeID]))
		keySet[empDay{*p.EmployeeID, d}] = true
		keySet[empDay{*p.EmployeeID, d.AddDate(0, 0, -1)}] = true
	}
	keys := make([]empDay, 0, len(keySet))
	for k := range keySet {
		keys = append(keys, k)
	}
	shifts, err := s.resolveShifts(ctx, tenantID, keys, st)
	if err != nil {
		return 0, err
	}
	workDay := func(p *ent.AttendancePunch) empDay {
		emp := *p.EmployeeID
		d := localDate(p.PunchedAt, zones.For(outletOf[emp]))
		prev := shifts[empDay{emp, d.AddDate(0, 0, -1)}]
		return empDay{emp, attributeWorkDate(p.PunchedAt, d, prev, st, zones.For(outletOf[emp], prev.OutletID))}
	}
	affected := map[empDay]bool{}
	for _, p := range pending {
		affected[workDay(p)] = true
	}
	groups := map[empDay][]punchLite{}
	punchIDs := map[empDay][]uuid.UUID{}
	sources := map[empDay]map[string]bool{}
	for _, p := range all {
		k := workDay(p)
		if !affected[k] {
			continue
		}
		groups[k] = append(groups[k], punchLite{ID: p.ID, At: p.PunchedAt, Status: p.Status})
		punchIDs[k] = append(punchIDs[k], p.ID)
		if sources[k] == nil {
			sources[k] = map[string]bool{}
		}
		sources[k][string(p.Source)] = true
	}

	rules, err := s.loadRuleSet(ctx, tenantID, empIDs)
	if err != nil {
		return 0, err
	}
	dlo, dhi := time.Time{}, time.Time{}
	for k := range affected {
		if dlo.IsZero() || k.Day.Before(dlo) {
			dlo = k.Day
		}
		if k.Day.After(dhi) {
			dhi = k.Day
		}
	}
	existingRows, err := s.orm.AttendanceRecord.Query().Where(
		attendancerecord.TenantID(tenantID), attendancerecord.EmployeeIDIn(empIDs...),
		attendancerecord.DateGTE(dlo), attendancerecord.DateLT(dhi.AddDate(0, 0, 1)),
	).All(ctx)
	if err != nil {
		return 0, fmt.Errorf("attendance: existing records: %w", err)
	}
	existing := map[empDay]*ent.AttendanceRecord{}
	for _, r := range existingRows {
		existing[empDay{r.EmployeeID, dateOnly(r.Date)}] = r
	}

	builders := make([]*ent.AttendanceRecordCreate, 0, len(groups))
	for k, ps := range groups {
		in, out := pairPunches(ps, st.PunchPairWindowMinutes)
		meta := map[string]any{}
		if ex := existing[k]; ex != nil {
			for mk, mv := range ex.Metadata {
				meta[mk] = mv
			}
			delete(meta, "auto_absent")
			in, out = mergeTimes(ex, in, out)
		}
		ds := shifts[k]
		outlet := outletOf[k.Emp]
		loc := zones.For(outlet, ds.OutletID)
		res := evaluate(evalInput{CheckIn: in, CheckOut: out, WorkDate: k.Day, Shift: ds, Loc: loc,
			Rule: rules.pick(k.Emp, outlet), Settings: st})
		stampResult(meta, res, ds)
		srcs := make([]string, 0, len(sources[k]))
		for src := range sources[k] {
			srcs = append(srcs, src)
		}
		meta["punch_sources"] = srcs
		meta["punch_count"] = len(ps)
		b := s.orm.AttendanceRecord.Create().
			SetTenantID(tenantID).SetEmployeeID(k.Emp).SetDate(k.Day).
			SetNillableCheckIn(in).SetNillableCheckOut(out).
			SetNillableOutletID(outlet).SetNillableWorkShiftID(ds.ShiftID).
			SetStatus(attendancerecord.Status(res.Status)).
			SetTotalSecondsWorked(res.Seconds).SetRegularHours(res.Regular).SetOvertimeHours(res.Overtime).
			SetMetadata(meta)
		builders = append(builders, b)
	}
	if len(builders) == 0 {
		return 0, nil
	}
	if err := s.orm.AttendanceRecord.CreateBulk(builders...).
		OnConflictColumns(attendancerecord.FieldTenantID, attendancerecord.FieldEmployeeID, attendancerecord.FieldDate).
		UpdateNewValues().Exec(ctx); err != nil {
		return 0, fmt.Errorf("attendance: upsert records: %w", err)
	}

	saved, err := s.orm.AttendanceRecord.Query().Where(
		attendancerecord.TenantID(tenantID), attendancerecord.EmployeeIDIn(empIDs...),
		attendancerecord.DateGTE(dlo), attendancerecord.DateLT(dhi.AddDate(0, 0, 1)),
	).All(ctx)
	if err != nil {
		return 0, fmt.Errorf("attendance: reload records: %w", err)
	}
	var pids, rids []uuid.UUID
	written := 0
	for _, r := range saved {
		k := empDay{r.EmployeeID, dateOnly(r.Date)}
		if !affected[k] {
			continue
		}
		for _, pid := range punchIDs[k] {
			pids = append(pids, pid)
			rids = append(rids, r.ID)
		}
		written++
		s.publishRecord(ctx, r)
	}
	if len(pids) > 0 {
		if _, err := s.orm.ExecContext(ctx, markPunchesSQL, pids, rids); err != nil {
			return written, fmt.Errorf("attendance: mark punches: %w", err)
		}
	}
	s.log.Debug("punches processed", zap.String("tenant", tenantID.String()), zap.Int("records", written))
	return written, nil
}

// mergeTimes keeps an earlier check-in or later check-out already on the record (an HR entry
// or an earlier clock-in that has no punch row) when it widens the punched day. An auto-absent
// placeholder has no times and changes nothing.
func mergeTimes(ex *ent.AttendanceRecord, in, out *time.Time) (*time.Time, *time.Time) {
	if ex.CheckIn != nil && (in == nil || ex.CheckIn.Before(*in)) {
		in = ex.CheckIn
	}
	if ex.CheckOut != nil && (out == nil || ex.CheckOut.After(*out)) {
		out = ex.CheckOut
	}
	return in, out
}
