package attendance

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"math"
	"time"

	"github.com/Bengo-Hub/httpware/geo"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancepunch"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
)

// Self clock-in errors, mapped to HTTP statuses by the handler.
var (
	ErrOutsideFence  = errors.New("attendance: you are outside every work site")
	ErrPhotoRequired = errors.New("attendance: a photo is required to clock in or out")
	ErrNotClockedIn  = errors.New("attendance: no clock-in found for today")
	ErrBadLocation   = errors.New("attendance: a valid location is required")
	ErrClockedIn     = errors.New("attendance: already clocked in today")
)

// AttendanceModeField marks staff who may clock in anywhere (every punch geo-tagged).
const AttendanceModeField = "field"

// SelfClockInput is an ESS clock-in or clock-out from a phone or browser.
type SelfClockInput struct {
	Lat, Lng  float64
	AccuracyM float64
	PhotoURL  string
	Note      string
	Source    string // mobile | web
}

// FenceResult is the geo-fence outcome returned to the caller and kept on the punch.
type FenceResult struct {
	Checked   bool       `json:"checked"`
	Inside    bool       `json:"inside"`
	DistanceM float64    `json:"distance_m"`
	SiteID    *uuid.UUID `json:"site_id,omitempty"`
	SiteName  string     `json:"site_name,omitempty"`
}

// SelfClockResult is the response of a self clock-in or clock-out.
type SelfClockResult struct {
	Record  *ent.AttendanceRecord `json:"record"`
	Fence   FenceResult           `json:"fence"`
	Flagged bool                  `json:"flagged"`
}

// geoDecision is what a fence check means for a punch under the tenant's geo mode. Pure.
func geoDecision(mode string, field bool, f FenceResult) (flagged, blocked bool) {
	if field || mode == GeoModeOff || !f.Checked || f.Inside {
		return false, false
	}
	if mode == GeoModeBlock {
		return false, true
	}
	return true, false
}

// toleranceFor is the fence tolerance for a fix: the reported accuracy capped by the tenant
// tolerance (a poor fix earns no more slack than HR allows).
func toleranceFor(accuracyM, maxM float64) float64 {
	if accuracyM <= 0 || math.IsNaN(accuracyM) {
		return 0
	}
	return math.Min(accuracyM, maxM)
}

// checkFence tests a point against the sites with httpware/geo.
func checkFence(p geo.Point, sites []*ent.WorkSite, toleranceM float64) FenceResult {
	if len(sites) == 0 {
		return FenceResult{}
	}
	fences := make([]geo.Fence, len(sites))
	for i, w := range sites {
		fences[i] = fenceOf(w)
	}
	idx, c, ok := geo.Nearest(p, fences, toleranceM)
	if !ok {
		return FenceResult{}
	}
	id := sites[idx].ID
	return FenceResult{Checked: true, Inside: c.Inside, DistanceM: math.Round(c.DistanceM*10) / 10,
		SiteID: &id, SiteName: sites[idx].Name}
}

func attendanceMode(emp *ent.Employee) string {
	if v, ok := emp.Metadata["attendance_mode"].(string); ok {
		return v
	}
	return "site"
}

// SelfClock clocks the caller's own employee in (out=false) or out. Outside every site the
// tenant geo mode decides: off ignores it, flag accepts and flags the punch and record for HR
// review, block refuses. Field staff are never flagged or blocked; their punches are tagged.
func (s *Service) SelfClock(ctx context.Context, tenantID, empID uuid.UUID, out bool, in SelfClockInput) (*SelfClockResult, error) {
	p := geo.Point{Lat: in.Lat, Lng: in.Lng}
	if !geo.Valid(p) || (p.Lat == 0 && p.Lng == 0) {
		return nil, ErrBadLocation
	}
	st, err := s.GetSettings(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	if st.RequirePhoto && in.PhotoURL == "" {
		return nil, ErrPhotoRequired
	}
	emp, err := s.loadEmployee(ctx, tenantID, empID)
	if err != nil {
		return nil, err
	}
	field := attendanceMode(emp) == AttendanceModeField
	var fence FenceResult
	if st.GeoMode != GeoModeOff || field {
		sites, err := s.sitesFor(ctx, tenantID, emp.OutletID)
		if err != nil {
			return nil, fmt.Errorf("attendance: work sites: %w", err)
		}
		fence = checkFence(p, sites, toleranceFor(in.AccuracyM, st.GeoToleranceM))
	}
	flagged, blocked := geoDecision(st.GeoMode, field, fence)
	if blocked {
		return &SelfClockResult{Fence: fence}, ErrOutsideFence
	}
	now := time.Now().UTC()
	geoMeta := map[string]any{"lat": in.Lat, "lng": in.Lng, "accuracy_m": in.AccuracyM,
		"checked": fence.Checked, "inside": fence.Inside, "distance_m": fence.DistanceM, "field": field}
	if fence.SiteID != nil {
		geoMeta["site_id"] = fence.SiteID.String()
		geoMeta["site_name"] = fence.SiteName
	}
	punchMeta := map[string]any{"geo": geoMeta}
	if in.PhotoURL != "" {
		punchMeta["photo_url"] = in.PhotoURL
	}
	if in.Note != "" {
		punchMeta["note"] = in.Note
	}
	source := in.Source
	if source != "web" {
		source = "mobile"
	}
	recMeta := map[string]any{"geo": geoMeta}
	if out {
		recMeta["geo_out"] = geoMeta
	} else {
		recMeta["geo_in"] = geoMeta
	}
	if in.PhotoURL != "" {
		if out {
			recMeta["photo_out_url"] = in.PhotoURL
		} else {
			recMeta["photo_in_url"] = in.PhotoURL
		}
	}
	if flagged {
		recMeta["flagged"] = true
	}
	if field {
		recMeta["attendance_mode"] = AttendanceModeField
	}

	dc, err := s.resolveDay(ctx, tenantID, emp, nil, time.Time{}, now, nil, false)
	if err != nil {
		return nil, err
	}
	open, err := s.orm.AttendanceRecord.Query().Where(
		attendancerecord.TenantID(tenantID), attendancerecord.EmployeeID(empID),
		attendancerecord.Date(dc.WorkDate), attendancerecord.CheckInNotNil()).Only(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return nil, fmt.Errorf("attendance: open record: %w", err)
	}
	var rec *ent.AttendanceRecord
	if out {
		if open == nil {
			return nil, ErrNotClockedIn
		}
		if open.Metadata["flagged"] == true {
			recMeta["flagged"] = true
		}
		rec, err = s.CheckOutWith(ctx, tenantID, open.ID, now, recMeta)
		if err != nil {
			return nil, err
		}
	} else {
		if open != nil {
			return &SelfClockResult{Record: open, Fence: fence}, ErrClockedIn
		}
		rec, err = s.CheckIn(ctx, tenantID, CheckInInput{EmployeeID: empID, Date: dc.WorkDate, CheckIn: now, Source: source,
			GPSLat: fmt.Sprintf("%.6f", in.Lat), GPSLng: fmt.Sprintf("%.6f", in.Lng), Metadata: recMeta})
		if err != nil {
			return nil, err
		}
	}
	status := 0
	if out {
		status = stateOut
	}
	if err := s.orm.AttendancePunch.Create().SetTenantID(tenantID).SetDevicePin(empID.String()).
		SetEmployeeID(empID).SetPunchedAt(now).SetStatus(status).
		SetSource(attendancepunch.Source(source)).SetProcessed(true).SetAttendanceRecordID(rec.ID).
		SetFlagged(flagged).SetMetadata(punchMeta).
		OnConflictColumns(attendancepunch.FieldDeviceSn, attendancepunch.FieldDevicePin, attendancepunch.FieldPunchedAt).
		DoNothing().Exec(ctx); err != nil && !errors.Is(err, sql.ErrNoRows) {
		s.log.Warn("self clock punch row not written", zap.Error(err))
	}
	return &SelfClockResult{Record: rec, Fence: fence, Flagged: flagged}, nil
}

// SelfToday is the ESS view of today: the record, the planned shift, the sites and the policy.
type SelfToday struct {
	Record *ent.AttendanceRecord `json:"record"`
	Shift  DayShift              `json:"shift"`
	Sites  []WorkSiteView        `json:"sites"`
	Policy map[string]any        `json:"policy"`
}

// Today returns the caller's attendance state for the current work day.
func (s *Service) Today(ctx context.Context, tenantID, empID uuid.UUID) (*SelfToday, error) {
	emp, err := s.loadEmployee(ctx, tenantID, empID)
	if err != nil {
		return nil, err
	}
	dc, err := s.resolveDay(ctx, tenantID, emp, nil, time.Time{}, time.Now(), nil, false)
	if err != nil {
		return nil, err
	}
	rec, err := s.orm.AttendanceRecord.Query().Where(attendancerecord.TenantID(tenantID),
		attendancerecord.EmployeeID(empID), attendancerecord.Date(dc.WorkDate)).Only(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return nil, fmt.Errorf("attendance: today record: %w", err)
	}
	sites, err := s.sitesFor(ctx, tenantID, emp.OutletID)
	if err != nil {
		return nil, fmt.Errorf("attendance: work sites: %w", err)
	}
	return &SelfToday{Record: rec, Shift: dc.Shift, Sites: WorkSiteViews(sites), Policy: map[string]any{
		"geo_mode": dc.Settings.GeoMode, "geo_tolerance_m": dc.Settings.GeoToleranceM,
		"require_photo": dc.Settings.RequirePhoto, "attendance_mode": attendanceMode(emp),
		"work_date": dc.WorkDate.Format("2006-01-02"),
	}}, nil
}
