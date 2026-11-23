package attendance

import (
	"context"
	"errors"
	"fmt"
	"net/netip"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancedevice"
	"github.com/Bengo-Hub/erp-api/internal/ent/devicecommand"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
)

// ErrUnknownDevice is returned for a serial that is not registered or not active.
var ErrUnknownDevice = errors.New("attendance: unknown or inactive device")

// ingestChunk bounds the rows sent in one INSERT ... SELECT FROM unnest.
const ingestChunk = 5000

// Handshake defaults; a device's metadata "options" map overrides any of them.
var defaultDeviceOptions = map[string]any{
	"error_delay": 30, "delay": 10, "trans_times": "00:00;14:05", "trans_interval": 1, "realtime": true,
}

// insertPunchesSQL bulk inserts device punches; a redelivered line hits the unique
// (device_sn, device_pin, punched_at) key and is skipped.
const insertPunchesSQL = `
INSERT INTO attendance_punches
  (id, tenant_id, device_id, device_sn, device_pin, employee_id, punched_at, status, verify_mode,
   work_code, source, processed, flagged, metadata, created_at)
SELECT gen_random_uuid(), $1, $2, $3, v.pin, NULLIF(v.emp, '')::uuid, v.at, v.status, v.verify,
       v.wc, 'device', false, false, jsonb_build_object('raw', v.raw), now()
FROM unnest($4::text[], $5::text[], $6::timestamptz[], $7::bigint[], $8::bigint[], $9::text[], $10::text[])
  AS v(pin, emp, at, status, verify, wc, raw)
ON CONFLICT (device_sn, device_pin, punched_at) DO NOTHING`

// insertAccessSQL bulk inserts access events, skipping redelivered ones.
const insertAccessSQL = `
INSERT INTO access_events
  (id, tenant_id, device_id, device_sn, device_pin, employee_id, occurred_at, door, result,
   event_code, verify_mode, in_out, metadata, created_at)
SELECT gen_random_uuid(), $1, $2, $3, v.pin, NULLIF(v.emp, '')::uuid, v.at, v.door, v.result,
       v.code, v.verify, v.inout, jsonb_build_object('raw', v.raw, 'card_no', v.card), now()
FROM unnest($4::text[], $5::text[], $6::timestamptz[], $7::bigint[], $8::text[], $9::bigint[],
            $10::bigint[], $11::bigint[], $12::text[], $13::text[])
  AS v(pin, emp, at, door, result, code, verify, inout, raw, card)
ON CONFLICT (device_sn, device_pin, occurred_at, door, event_code) DO NOTHING`

// DeviceBySerial loads an active registered device for the public endpoints.
func (s *Service) DeviceBySerial(ctx context.Context, sn string) (*ent.AttendanceDevice, error) {
	sn = strings.TrimSpace(sn)
	if sn == "" {
		return nil, ErrUnknownDevice
	}
	dev, err := s.orm.AttendanceDevice.Query().Where(attendancedevice.SerialNumber(sn)).Only(ctx)
	if ent.IsNotFound(err) || (err == nil && !dev.Active) {
		return nil, ErrUnknownDevice
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: device lookup: %w", err)
	}
	return dev, nil
}

// deviceZone is the device's own zone, else its outlet's, else the tenant's.
func (s *Service) deviceZone(ctx context.Context, dev *ent.AttendanceDevice) *time.Location {
	zones, err := s.loadZones(ctx, dev.TenantID)
	if err != nil {
		loc, _ := time.LoadLocation(defaultZone)
		return loc
	}
	return zones.Named(dev.Timezone, dev.OutletID)
}

// seenWriteInterval is how often a polling device's last_seen_at is refreshed when nothing
// else changed. Terminals poll every few seconds; writing each poll would be pure churn.
const seenWriteInterval = 30 * time.Second

// DeviceAllowsIP reports whether ip may speak for dev. A device with no
// metadata.allowed_cidrs (list of CIDRs or single addresses) accepts any address; with a
// list, only matching addresses are admitted, so a copied serial alone cannot push punches.
func DeviceAllowsIP(dev *ent.AttendanceDevice, ip string) bool {
	raw, ok := dev.Metadata["allowed_cidrs"].([]any)
	if !ok || len(raw) == 0 {
		return true
	}
	addr, err := netip.ParseAddr(strings.TrimSpace(ip))
	if err != nil {
		return false
	}
	addr = addr.Unmap()
	for _, v := range raw {
		s, _ := v.(string)
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		if !strings.Contains(s, "/") {
			if a, err := netip.ParseAddr(s); err == nil && a.Unmap() == addr {
				return true
			}
			continue
		}
		if p, err := netip.ParsePrefix(s); err == nil && p.Contains(addr) {
			return true
		}
	}
	return false
}

// DeviceSeen records a contact: last seen, IP, push version and whatever INFO reported. A
// plain poll with nothing new within seenWriteInterval of the last write is skipped.
func (s *Service) DeviceSeen(ctx context.Context, dev *ent.AttendanceDevice, ip, pushVer, info string) {
	now := time.Now().UTC()
	if pushVer == "" && info == "" && (ip == "" || ip == dev.LastIP) &&
		dev.LastSeenAt != nil && now.Sub(*dev.LastSeenAt) < seenWriteInterval {
		return
	}
	if ip != "" && dev.LastIP != "" && ip != dev.LastIP {
		s.log.Warn("device address changed", zap.String("sn", dev.SerialNumber),
			zap.String("from", dev.LastIP), zap.String("to", ip))
	}
	u := s.orm.AttendanceDevice.UpdateOneID(dev.ID).SetLastSeenAt(now)
	if ip != "" {
		u = u.SetLastIP(ip)
	}
	if pushVer != "" {
		u = u.SetPushVersion(pushVer)
	}
	if di, ok := ParseInfo(info); ok {
		u = u.SetFirmware(di.Firmware).SetUserCount(di.UserCount).SetPunchCount(di.PunchCount)
	}
	if err := u.Exec(ctx); err != nil {
		s.log.Warn("device seen update failed", zap.String("sn", dev.SerialNumber), zap.Error(err))
	}
}

// DeviceHandshake answers GET /iclock/cdata with the options block.
func (s *Service) DeviceHandshake(ctx context.Context, dev *ent.AttendanceDevice) string {
	opts := map[string]any{}
	for k, v := range defaultDeviceOptions {
		opts[k] = v
	}
	if o, ok := dev.Metadata["options"].(map[string]any); ok {
		for k, v := range o {
			opts[k] = v
		}
	}
	_, offset := time.Now().In(s.deviceZone(ctx, dev)).Zone()
	return HandshakeBody(dev.SerialNumber, HandshakeOptions{
		ATTLOGStamp:   metaString(dev.Metadata, "attlog_stamp"),
		OPERLOGStamp:  metaString(dev.Metadata, "operlog_stamp"),
		ErrorDelay:    anyInt(opts["error_delay"]),
		Delay:         anyInt(opts["delay"]),
		TransTimes:    fmt.Sprint(opts["trans_times"]),
		TransInterval: anyInt(opts["trans_interval"]),
		Realtime:      opts["realtime"] == true,
		TZOffsetHours: offset / 3600,
	})
}

// UploadResult summarises a device upload.
type UploadResult struct {
	Table      string `json:"table"`
	Received   int    `json:"received"`
	Inserted   int64  `json:"inserted"`
	Duplicates int64  `json:"duplicates"`
	Unmatched  int    `json:"unmatched"`
	Skipped    int    `json:"skipped"`
}

// DeviceUpload handles POST /iclock/cdata for one table. Unknown tables are accepted and
// ignored so the device moves on.
func (s *Service) DeviceUpload(ctx context.Context, dev *ent.AttendanceDevice, table, stamp, body string) (UploadResult, error) {
	res := UploadResult{Table: table}
	var err error
	switch strings.ToUpper(table) {
	case "ATTLOG":
		res, err = s.ingestATTLOG(ctx, dev, body)
		if err == nil {
			s.saveDeviceMeta(ctx, dev, "attlog_stamp", stamp)
		}
	case "OPERLOG":
		ol := ParseOPERLOG(body)
		res.Received = len(ol.Users) + ol.Ops + ol.Other
		s.saveDeviceMeta(ctx, dev, "operlog_stamp", stamp)
	case "RTLOG":
		res, err = s.ingestRTLog(ctx, dev, body)
	case "OPTIONS":
		kv := parseKV(strings.TrimPrefix(strings.TrimSpace(body), "~"), ",")
		if fw := kv["FWVersion"]; fw != "" {
			_ = s.orm.AttendanceDevice.UpdateOneID(dev.ID).SetFirmware(fw).Exec(ctx)
		}
	}
	res.Table = table
	return res, err
}

// saveDeviceMeta stores one string in the device metadata when it is set.
func (s *Service) saveDeviceMeta(ctx context.Context, dev *ent.AttendanceDevice, key, val string) {
	if val == "" {
		return
	}
	meta := map[string]any{}
	for k, v := range dev.Metadata {
		meta[k] = v
	}
	meta[key] = val
	if err := s.orm.AttendanceDevice.UpdateOneID(dev.ID).SetMetadata(meta).Exec(ctx); err != nil {
		s.log.Warn("device metadata update failed", zap.String("sn", dev.SerialNumber), zap.Error(err))
	}
}

// pinEmployees maps device PINs to the tenant's employees.
func (s *Service) pinEmployees(ctx context.Context, tenantID uuid.UUID, pins []string) (map[string]uuid.UUID, error) {
	out := map[string]uuid.UUID{}
	if len(pins) == 0 {
		return out, nil
	}
	rows, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.DevicePinIn(pins...)).
		Select(employee.FieldID, employee.FieldDevicePin).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: pin lookup: %w", err)
	}
	for _, e := range rows {
		if e.DevicePin != nil {
			out[*e.DevicePin] = e.ID
		}
	}
	return out, nil
}

func uniquePins[T any](rows []T, pin func(T) string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, r := range rows {
		if p := pin(r); p != "" && !seen[p] {
			seen[p] = true
			out = append(out, p)
		}
	}
	return out
}

// ingestATTLOG stores an ATTLOG batch idempotently and starts the processor.
func (s *Service) ingestATTLOG(ctx context.Context, dev *ent.AttendanceDevice, body string) (UploadResult, error) {
	parsed, skipped := ParseATTLOG(body, s.deviceZone(ctx, dev))
	res := UploadResult{Table: "ATTLOG", Received: len(parsed), Skipped: skipped}
	if len(parsed) == 0 {
		return res, nil
	}
	emps, err := s.pinEmployees(ctx, dev.TenantID, uniquePins(parsed, func(p ParsedPunch) string { return p.PIN }))
	if err != nil {
		return res, err
	}
	for start := 0; start < len(parsed); start += ingestChunk {
		end := min(start+ingestChunk, len(parsed))
		n := end - start
		pins, empIDs, wcs, raws := make([]string, n), make([]string, n), make([]string, n), make([]string, n)
		ats := make([]time.Time, n)
		sts, vers := make([]int64, n), make([]int64, n)
		for i, p := range parsed[start:end] {
			pins[i], ats[i], sts[i], vers[i], wcs[i], raws[i] = p.PIN, p.At.UTC(), int64(p.Status), int64(p.Verify), p.WorkCode, p.Raw
			if id, ok := emps[p.PIN]; ok {
				empIDs[i] = id.String()
			} else {
				res.Unmatched++
			}
		}
		r, err := s.orm.ExecContext(ctx, insertPunchesSQL, dev.TenantID, dev.ID, dev.SerialNumber,
			pins, empIDs, ats, sts, vers, wcs, raws)
		if err != nil {
			return res, fmt.Errorf("attendance: insert punches: %w", err)
		}
		if c, rerr := r.RowsAffected(); rerr == nil {
			res.Inserted += c
		}
	}
	res.Duplicates = int64(res.Received) - res.Inserted
	if res.Inserted > 0 {
		s.publish(ctx, dev.TenantID, dev.ID, "attendance.punch.received", map[string]any{
			"device_id": dev.ID.String(), "serial": dev.SerialNumber, "inserted": res.Inserted,
			"duplicates": res.Duplicates, "unmatched": res.Unmatched,
		})
		s.KickProcessor(dev.TenantID)
	}
	return res, nil
}

// ingestRTLog stores access-control events idempotently.
func (s *Service) ingestRTLog(ctx context.Context, dev *ent.AttendanceDevice, body string) (UploadResult, error) {
	parsed, skipped := ParseRTLog(body, s.deviceZone(ctx, dev))
	res := UploadResult{Table: "rtlog", Received: len(parsed), Skipped: skipped}
	if len(parsed) == 0 {
		return res, nil
	}
	emps, err := s.pinEmployees(ctx, dev.TenantID, uniquePins(parsed, func(p ParsedAccess) string { return p.PIN }))
	if err != nil {
		return res, err
	}
	n := len(parsed)
	pins, empIDs, results, raws, cards := make([]string, n), make([]string, n), make([]string, n), make([]string, n), make([]string, n)
	ats := make([]time.Time, n)
	doors, codes, vers, inouts := make([]int64, n), make([]int64, n), make([]int64, n), make([]int64, n)
	for i, p := range parsed {
		pins[i], ats[i], doors[i], codes[i], vers[i], inouts[i], raws[i], cards[i] =
			p.PIN, p.At.UTC(), int64(p.Door), int64(p.Event), int64(p.Verify), int64(p.InOut), p.Raw, p.CardNo
		results[i] = "denied"
		if p.Granted {
			results[i] = "granted"
		}
		if id, ok := emps[p.PIN]; ok {
			empIDs[i] = id.String()
		} else if p.PIN != "" {
			res.Unmatched++
		}
	}
	r, err := s.orm.ExecContext(ctx, insertAccessSQL, dev.TenantID, dev.ID, dev.SerialNumber,
		pins, empIDs, ats, doors, results, codes, vers, inouts, raws, cards)
	if err != nil {
		return res, fmt.Errorf("attendance: insert access events: %w", err)
	}
	if c, rerr := r.RowsAffected(); rerr == nil {
		res.Inserted = c
	}
	res.Duplicates = int64(res.Received) - res.Inserted
	return res, nil
}

// DevicePoll answers GET /iclock/getrequest: the queued commands, marked sent, or "OK".
func (s *Service) DevicePoll(ctx context.Context, dev *ent.AttendanceDevice) (string, error) {
	cmds, err := s.orm.DeviceCommand.Query().Where(
		devicecommand.DeviceID(dev.ID), devicecommand.StatusEQ(devicecommand.StatusQueued),
	).Order(ent.Asc(devicecommand.FieldCmdNo)).Limit(20).All(ctx)
	if err != nil {
		return "OK", fmt.Errorf("attendance: queued commands: %w", err)
	}
	if len(cmds) == 0 {
		return "OK", nil
	}
	ids := make([]uuid.UUID, len(cmds))
	lines := make([]QueuedCommand, len(cmds))
	for i, c := range cmds {
		ids[i] = c.ID
		lines[i] = QueuedCommand{No: c.CmdNo, Line: c.Command}
	}
	if err := s.orm.DeviceCommand.Update().Where(devicecommand.IDIn(ids...)).
		SetStatus(devicecommand.StatusSent).SetSentAt(time.Now().UTC()).Exec(ctx); err != nil {
		return "OK", fmt.Errorf("attendance: mark commands sent: %w", err)
	}
	return CommandLines(lines), nil
}

// DeviceCommandReply handles POST /iclock/devicecmd: each reply closes its command. A
// non-negative Return is success on this protocol.
func (s *Service) DeviceCommandReply(ctx context.Context, dev *ent.AttendanceDevice, body string) (int, error) {
	n := 0
	now := time.Now().UTC()
	for _, r := range ParseCommandResults(body) {
		status := devicecommand.StatusDone
		if r.Return < 0 {
			status = devicecommand.StatusFailed
		}
		c, err := s.orm.DeviceCommand.Update().
			Where(devicecommand.DeviceID(dev.ID), devicecommand.CmdNo(r.ID)).
			SetStatus(status).SetReturnCode(r.Return).SetResult(r.CMD).SetCompletedAt(now).Save(ctx)
		if err != nil {
			return n, fmt.Errorf("attendance: close command: %w", err)
		}
		n += c
	}
	return n, nil
}

// running guards KickProcessor so a tenant has at most one in-process run at a time.
var running sync.Map

// KickProcessor pairs a tenant's pending punches in the background. A run already in progress
// for the tenant picks the new punches up on its next round or the cron sweep does.
func (s *Service) KickProcessor(tenantID uuid.UUID) {
	if _, busy := running.LoadOrStore(tenantID, true); busy {
		return
	}
	go func() {
		defer running.Delete(tenantID)
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer cancel()
		if _, err := s.ProcessPendingPunches(ctx, tenantID); err != nil {
			s.log.Error("punch processing failed", zap.String("tenant", tenantID.String()), zap.Error(err))
		}
	}()
}

func metaString(m map[string]any, k string) string {
	if v, ok := m[k].(string); ok {
		return v
	}
	return ""
}

func anyInt(v any) int {
	switch n := v.(type) {
	case int:
		return n
	case int64:
		return int(n)
	case float64:
		return int(n)
	case string:
		return atoiOr(n, 0)
	}
	return 0
}
