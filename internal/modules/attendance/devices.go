package attendance

import (
	"context"
	"errors"
	"fmt"
	"net/netip"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/accessevent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancedevice"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancepunch"
	"github.com/Bengo-Hub/erp-api/internal/ent/devicecommand"
	"github.com/Bengo-Hub/erp-api/internal/ent/worksite"
)

// Device errors, mapped to HTTP statuses by the handler.
var (
	ErrDeviceNotFound = errors.New("attendance: device not found")
	ErrSerialTaken    = errors.New("attendance: this serial number is already registered")
)

// DeviceInput is the create/patch payload for a device. Nil fields are left unchanged on patch.
type DeviceInput struct {
	Serial     *string
	Name       *string
	OutletID   *uuid.UUID
	WorkSiteID *uuid.UUID
	Mode       *string
	Active     *bool
	Timezone   *string
	Options    map[string]any // handshake option overrides, stored in metadata
	CommKey    *string
	// AllowedCIDRs, when set, replaces metadata.allowed_cidrs (see DeviceAllowsIP).
	AllowedCIDRs *[]string
}

// DeviceView is a device with its live status.
type DeviceView struct {
	*ent.AttendanceDevice
	// Serial mirrors serial_number under the contract's name.
	Serial          string   `json:"serial"`
	AllowedCIDRs    []string `json:"allowed_cidrs"`
	HasCommKey      bool     `json:"has_comm_key"`
	Online          bool     `json:"online"`
	PunchCountToday int      `json:"punch_count_today"`
	// EventCountToday counts today's door events; an access-control device reports these
	// instead of punches.
	EventCountToday int `json:"event_count_today"`
	// WorkSiteName and SiteOutletID describe the device's work site, so a device without an
	// outlet of its own can show the site's branch.
	WorkSiteName string     `json:"work_site_name"`
	SiteOutletID *uuid.UUID `json:"site_outlet_id"`
	// Metadata shadows the embedded field so the comm key never leaves the server.
	Metadata map[string]any `json:"metadata,omitempty"`
}

// newDeviceView builds the API view of a device with secrets removed from metadata.
func newDeviceView(dev *ent.AttendanceDevice, online bool, today int) DeviceView {
	v := DeviceView{AttendanceDevice: dev, Serial: dev.SerialNumber, Online: online,
		PunchCountToday: today, AllowedCIDRs: []string{}, Metadata: map[string]any{}}
	for k, val := range dev.Metadata {
		switch k {
		case "comm_key":
			v.HasCommKey = metaString(dev.Metadata, "comm_key") != ""
		case "allowed_cidrs":
			if list, ok := val.([]any); ok {
				for _, c := range list {
					if s, ok := c.(string); ok {
						v.AllowedCIDRs = append(v.AllowedCIDRs, s)
					}
				}
			}
		default:
			v.Metadata[k] = val
		}
	}
	return v
}

// CreateDevice registers a device for the tenant.
func (s *Service) CreateDevice(ctx context.Context, tenantID uuid.UUID, in DeviceInput) (*ent.AttendanceDevice, error) {
	if in.Serial == nil || strings.TrimSpace(*in.Serial) == "" {
		return nil, errors.New("serial is required")
	}
	name := strings.TrimSpace(*in.Serial)
	if in.Name != nil && strings.TrimSpace(*in.Name) != "" {
		name = strings.TrimSpace(*in.Name)
	}
	b := s.orm.AttendanceDevice.Create().SetTenantID(tenantID).
		SetSerialNumber(strings.TrimSpace(*in.Serial)).SetName(name).
		SetNillableOutletID(in.OutletID).SetNillableWorkSiteID(in.WorkSiteID).
		SetMetadata(deviceMeta(nil, in))
	if in.Mode != nil {
		b = b.SetMode(attendancedevice.Mode(*in.Mode))
	}
	if in.Active != nil {
		b = b.SetActive(*in.Active)
	}
	if in.Timezone != nil {
		if err := validZone(*in.Timezone); err != nil {
			return nil, err
		}
		b = b.SetTimezone(*in.Timezone)
	}
	row, err := b.Save(ctx)
	if ent.IsConstraintError(err) {
		return nil, ErrSerialTaken
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: create device: %w", err)
	}
	return row, nil
}

// UpdateDevice patches a tenant device.
func (s *Service) UpdateDevice(ctx context.Context, tenantID, id uuid.UUID, in DeviceInput) (*ent.AttendanceDevice, error) {
	dev, err := s.getDevice(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	u := dev.Update().SetMetadata(deviceMeta(dev.Metadata, in))
	if in.Serial != nil && strings.TrimSpace(*in.Serial) != "" {
		u = u.SetSerialNumber(strings.TrimSpace(*in.Serial))
	}
	if in.Name != nil {
		u = u.SetName(*in.Name)
	}
	if in.OutletID != nil {
		u = u.SetOutletID(*in.OutletID)
	}
	if in.WorkSiteID != nil {
		u = u.SetWorkSiteID(*in.WorkSiteID)
	}
	if in.Mode != nil {
		u = u.SetMode(attendancedevice.Mode(*in.Mode))
	}
	if in.Active != nil {
		u = u.SetActive(*in.Active)
	}
	if in.Timezone != nil {
		if err := validZone(*in.Timezone); err != nil {
			return nil, err
		}
		u = u.SetTimezone(*in.Timezone)
	}
	row, err := u.Save(ctx)
	if ent.IsConstraintError(err) {
		return nil, ErrSerialTaken
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: update device: %w", err)
	}
	return row, nil
}

func validZone(z string) error {
	if z == "" {
		return nil
	}
	if _, err := time.LoadLocation(z); err != nil {
		return fmt.Errorf("timezone %q is not a known IANA zone", z)
	}
	return nil
}

// deviceMeta merges the option overrides and comm key into existing metadata.
func deviceMeta(cur map[string]any, in DeviceInput) map[string]any {
	meta := map[string]any{}
	for k, v := range cur {
		meta[k] = v
	}
	if in.Options != nil {
		meta["options"] = in.Options
	}
	if in.CommKey != nil {
		meta["comm_key"] = *in.CommKey
	}
	if in.AllowedCIDRs != nil {
		list := make([]any, 0, len(*in.AllowedCIDRs))
		for _, c := range *in.AllowedCIDRs {
			if c = strings.TrimSpace(c); c != "" {
				list = append(list, c)
			}
		}
		if len(list) == 0 {
			delete(meta, "allowed_cidrs")
		} else {
			meta["allowed_cidrs"] = list
		}
	}
	return meta
}

// ValidCIDROrAddr reports whether s is a CIDR prefix or a single IP address.
func ValidCIDROrAddr(s string) bool {
	s = strings.TrimSpace(s)
	if strings.Contains(s, "/") {
		_, err := netip.ParsePrefix(s)
		return err == nil
	}
	_, err := netip.ParseAddr(s)
	return err == nil
}

// DeleteDevice removes a tenant device and its command queue. Punches and access events stay.
func (s *Service) DeleteDevice(ctx context.Context, tenantID, id uuid.UUID) error {
	if _, err := s.getDevice(ctx, tenantID, id); err != nil {
		return err
	}
	if _, err := s.orm.DeviceCommand.Delete().Where(devicecommand.TenantID(tenantID), devicecommand.DeviceID(id)).Exec(ctx); err != nil {
		return fmt.Errorf("attendance: delete device commands: %w", err)
	}
	return s.orm.AttendanceDevice.DeleteOneID(id).Exec(ctx)
}

func (s *Service) getDevice(ctx context.Context, tenantID, id uuid.UUID) (*ent.AttendanceDevice, error) {
	dev, err := s.orm.AttendanceDevice.Query().Where(attendancedevice.TenantID(tenantID), attendancedevice.ID(id)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, ErrDeviceNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: load device: %w", err)
	}
	return dev, nil
}

// GetDevice returns one device with its live status.
func (s *Service) GetDevice(ctx context.Context, tenantID, id uuid.UUID) (*DeviceView, error) {
	dev, err := s.getDevice(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	views, err := s.deviceViews(ctx, tenantID, []*ent.AttendanceDevice{dev})
	if err != nil {
		return nil, err
	}
	return &views[0], nil
}

// ListDevices returns the tenant's devices with online status and today's punch count.
func (s *Service) ListDevices(ctx context.Context, tenantID uuid.UUID) ([]DeviceView, error) {
	rows, err := s.orm.AttendanceDevice.Query().Where(attendancedevice.TenantID(tenantID)).
		Order(ent.Asc(attendancedevice.FieldName)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: list devices: %w", err)
	}
	return s.deviceViews(ctx, tenantID, rows)
}

func (s *Service) deviceViews(ctx context.Context, tenantID uuid.UUID, rows []*ent.AttendanceDevice) ([]DeviceView, error) {
	st, err := s.GetSettings(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	zones, err := s.loadZones(ctx, tenantID)
	if err != nil {
		return nil, fmt.Errorf("attendance: zones: %w", err)
	}
	now := time.Now()
	y, m, d := now.In(zones.For()).Date()
	dayStart := time.Date(y, m, d, 0, 0, 0, 0, zones.For())
	var counts []struct {
		DeviceID uuid.UUID `json:"device_id"`
		Count    int       `json:"count"`
	}
	if len(rows) > 0 {
		if err := s.orm.AttendancePunch.Query().Where(
			attendancepunch.TenantID(tenantID), attendancepunch.DeviceIDNotNil(),
			attendancepunch.PunchedAtGTE(dayStart),
		).GroupBy(attendancepunch.FieldDeviceID).Aggregate(ent.Count()).Scan(ctx, &counts); err != nil {
			return nil, fmt.Errorf("attendance: device punch counts: %w", err)
		}
	}
	byDev := map[uuid.UUID]int{}
	for _, c := range counts {
		byDev[c.DeviceID] = c.Count
	}
	var events []struct {
		DeviceID uuid.UUID `json:"device_id"`
		Count    int       `json:"count"`
	}
	siteIDs := make([]*uuid.UUID, 0, len(rows))
	for _, r := range rows {
		siteIDs = append(siteIDs, r.WorkSiteID)
	}
	if len(rows) > 0 {
		if err := s.orm.AccessEvent.Query().Where(
			accessevent.TenantID(tenantID), accessevent.OccurredAtGTE(dayStart),
		).GroupBy(accessevent.FieldDeviceID).Aggregate(ent.Count()).Scan(ctx, &events); err != nil {
			return nil, fmt.Errorf("attendance: device event counts: %w", err)
		}
	}
	eventsByDev := map[uuid.UUID]int{}
	for _, c := range events {
		eventsByDev[c.DeviceID] = c.Count
	}
	sites := map[uuid.UUID]*ent.WorkSite{}
	if ids := uniq(siteIDs...); len(ids) > 0 {
		ss, err := s.orm.WorkSite.Query().Where(worksite.TenantID(tenantID), worksite.IDIn(ids...)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: device work sites: %w", err)
		}
		for _, ws := range ss {
			sites[ws.ID] = ws
		}
	}
	window := time.Duration(st.DeviceOnlineMinutes) * time.Minute
	out := make([]DeviceView, len(rows))
	for i, r := range rows {
		v := newDeviceView(r, r.LastSeenAt != nil && now.Sub(*r.LastSeenAt) <= window, byDev[r.ID])
		v.EventCountToday = eventsByDev[r.ID]
		if r.WorkSiteID != nil {
			if ws, ok := sites[*r.WorkSiteID]; ok {
				v.WorkSiteName, v.SiteOutletID = ws.Name, ws.OutletID
			}
		}
		out[i] = v
	}
	return out, nil
}

// Command types accepted by EnqueueCommand.
var commandTypes = map[string]bool{"sync_users": true, "open_door": true, "reboot": true, "reload_logs": true, "clear_logs": true}

// CommandInput is a command request.
type CommandInput struct {
	Type      string
	From, To  *time.Time // reload_logs range; defaults to the last 7 days
	CreatedBy *uuid.UUID
}

// EnqueueCommand queues protocol commands for a device; sync_users queues one per employee
// with a device PIN (those of the device's outlet, plus those without an outlet).
func (s *Service) EnqueueCommand(ctx context.Context, tenantID, deviceID uuid.UUID, in CommandInput) ([]*ent.DeviceCommand, error) {
	if !commandTypes[in.Type] {
		return nil, fmt.Errorf("type must be one of sync_users, open_door, reboot, reload_logs, clear_logs")
	}
	dev, err := s.getDevice(ctx, tenantID, deviceID)
	if err != nil {
		return nil, err
	}
	var lines []string
	switch in.Type {
	case "sync_users":
		users, err := s.deviceUsers(ctx, tenantID, dev)
		if err != nil {
			return nil, err
		}
		for _, u := range users {
			lines = append(lines, UserInfoCommand(u.PIN, u.Name))
		}
		if len(lines) == 0 {
			return nil, errors.New("no employees with a device PIN for this device")
		}
	case "open_door":
		line := metaString(dev.Metadata, "open_door_command")
		if line == "" {
			line = "CONTROL DEVICE 01010105"
		}
		lines = []string{line}
	case "reboot":
		lines = []string{"REBOOT"}
	case "clear_logs":
		lines = []string{"CLEAR LOG"}
	case "reload_logs":
		loc := s.deviceZone(ctx, dev)
		to := time.Now()
		if in.To != nil {
			to = in.To.Add(24*time.Hour - time.Second)
		}
		from := to.AddDate(0, 0, -7)
		if in.From != nil {
			from = *in.From
		}
		lines = []string{fmt.Sprintf("DATA QUERY ATTLOG StartTime=%s\tEndTime=%s",
			from.In(loc).Format(admsTimeLayout), to.In(loc).Format(admsTimeLayout))}
	}
	return s.queueLines(ctx, dev, in.Type, lines, in.CreatedBy)
}

// queueLines inserts the command rows with the next per-device numbers, retrying once when a
// concurrent enqueue took the same numbers.
func (s *Service) queueLines(ctx context.Context, dev *ent.AttendanceDevice, typ string, lines []string, by *uuid.UUID) ([]*ent.DeviceCommand, error) {
	for attempt := 0; attempt < 2; attempt++ {
		next := int64(1)
		last, err := s.orm.DeviceCommand.Query().Where(devicecommand.DeviceID(dev.ID)).
			Order(ent.Desc(devicecommand.FieldCmdNo)).First(ctx)
		if err == nil {
			next = last.CmdNo + 1
		} else if !ent.IsNotFound(err) {
			return nil, fmt.Errorf("attendance: last command: %w", err)
		}
		bs := make([]*ent.DeviceCommandCreate, len(lines))
		for i, l := range lines {
			bs[i] = s.orm.DeviceCommand.Create().SetTenantID(dev.TenantID).SetDeviceID(dev.ID).
				SetCmdNo(next + int64(i)).SetCommandType(typ).SetCommand(l).SetNillableCreatedBy(by)
		}
		rows, err := s.orm.DeviceCommand.CreateBulk(bs...).Save(ctx)
		if ent.IsConstraintError(err) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("attendance: queue commands: %w", err)
		}
		return rows, nil
	}
	return nil, errors.New("attendance: command queue busy, try again")
}

// ListCommands returns a device's commands, newest first.
func (s *Service) ListCommands(ctx context.Context, tenantID, deviceID uuid.UUID, limit, offset int) ([]*ent.DeviceCommand, int, error) {
	q := s.orm.DeviceCommand.Query().Where(devicecommand.TenantID(tenantID), devicecommand.DeviceID(deviceID))
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, err
	}
	rows, err := q.Order(ent.Desc(devicecommand.FieldCmdNo)).Limit(limit).Offset(offset).All(ctx)
	return rows, total, err
}

// PunchFilter narrows a punch list.
type PunchFilter struct {
	From, To   *time.Time
	DeviceID   *uuid.UUID
	EmployeeID *uuid.UUID
	Unmatched  bool
	Flagged    *bool
}

// ListPunches returns raw punches over a bounded range, newest first.
func (s *Service) ListPunches(ctx context.Context, tenantID uuid.UUID, f PunchFilter, limit, offset int) ([]*ent.AttendancePunch, int, error) {
	lo, hi := s.instantRange(ctx, tenantID, f.From, f.To)
	q := s.orm.AttendancePunch.Query().Where(attendancepunch.TenantID(tenantID),
		attendancepunch.PunchedAtGTE(lo), attendancepunch.PunchedAtLT(hi))
	if f.DeviceID != nil {
		q = q.Where(attendancepunch.DeviceID(*f.DeviceID))
	}
	if f.EmployeeID != nil {
		q = q.Where(attendancepunch.EmployeeID(*f.EmployeeID))
	}
	if f.Unmatched {
		q = q.Where(attendancepunch.EmployeeIDIsNil())
	}
	if f.Flagged != nil {
		q = q.Where(attendancepunch.Flagged(*f.Flagged))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("attendance: count punches: %w", err)
	}
	rows, err := q.Order(ent.Desc(attendancepunch.FieldPunchedAt)).Limit(limit).Offset(offset).All(ctx)
	return rows, total, err
}

// AccessFilter narrows an access event list.
type AccessFilter struct {
	From, To *time.Time
	DeviceID *uuid.UUID
	Result   string
	Door     *int
}

// ListAccessEvents returns door events over a bounded range, newest first.
func (s *Service) ListAccessEvents(ctx context.Context, tenantID uuid.UUID, f AccessFilter, limit, offset int) ([]*ent.AccessEvent, int, error) {
	lo, hi := s.instantRange(ctx, tenantID, f.From, f.To)
	q := s.orm.AccessEvent.Query().Where(accessevent.TenantID(tenantID),
		accessevent.OccurredAtGTE(lo), accessevent.OccurredAtLT(hi))
	if f.DeviceID != nil {
		q = q.Where(accessevent.DeviceID(*f.DeviceID))
	}
	if f.Result == "granted" || f.Result == "denied" {
		q = q.Where(accessevent.ResultEQ(accessevent.Result(f.Result)))
	}
	if f.Door != nil {
		q = q.Where(accessevent.Door(*f.Door))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("attendance: count access events: %w", err)
	}
	rows, err := q.Order(ent.Desc(accessevent.FieldOccurredAt)).Limit(limit).Offset(offset).All(ctx)
	return rows, total, err
}

// instantRange turns an optional local date range into instants in the tenant zone: from the
// start of the first day to the start of the day after the last, bounded like record lists.
func (s *Service) instantRange(ctx context.Context, tenantID uuid.UUID, from, to *time.Time) (time.Time, time.Time) {
	lo, hi := boundRange(from, to, time.Now())
	loc, _ := time.LoadLocation(defaultZone)
	if zones, err := s.loadZones(ctx, tenantID); err == nil {
		loc = zones.For()
	}
	start, _ := clockOn(lo, "00:00", loc)
	end, _ := clockOn(hi.AddDate(0, 0, 1), "00:00", loc)
	return start, end
}
