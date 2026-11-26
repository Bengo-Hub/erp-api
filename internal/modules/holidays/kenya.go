package holidays

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/publicholiday"
)

// SeededKey is the system tenant's AppSetting listing the platform holidays already seeded, so one
// the platform owner renamed, moved or deleted does not come back on the next deploy.
const SeededKey = "holidays.seeded"

type dated struct{ date, name string }

// kenya is the national calendar from December 2026: the fixed-date days in Part I of the Schedule
// to the Public Holidays Act (Cap. 110, version of 26 April 2024, https://kenyalaw.org/akn/ke/act/1912/21/eng@2024-04-26).
// The Statute Law (Miscellaneous Amendments) Act, 2024 (Act No. 3 of 2024) put Mazingira Day on
// 10 October. Section 4: "Where, in any year, a day in Part I of the Schedule falls on a Sunday,
// then the first succeeding day, not being a public holiday, shall be a public holiday and the
// first-mentioned day shall cease to be a public holiday." Good Friday and Easter Monday follow
// Easter Sunday, 28 March 2027.
//
// Idd-ul-Fitr (Part I) has no fixed date ("depending upon the appearance of the moon"); the
// Minister declares the day by Gazette notice, so the platform owner adds it once declared.
// Idd-ul-Azha is in Part II (for persons of the Islamic faith) and Diwali in Part III (Hindu faith);
// either is national only in a year a Gazette notice under section 3 makes it so. Days in months
// already paid are left out, so no closed payroll changes.
var kenya = []dated{
	{"2026-12-12", "Jamhuri Day"},
	{"2026-12-25", "Christmas Day"},
	{"2026-12-26", "Boxing Day"},
	{"2027-01-01", "New Year's Day"},
	{"2027-03-26", "Good Friday"},
	{"2027-03-29", "Easter Monday"},
	{"2027-05-01", "Labour Day"},
	{"2027-06-01", "Madaraka Day"},
	{"2027-10-10", "Mazingira Day"},
	{"2027-10-20", "Mashujaa Day"},
	{"2027-12-12", "Jamhuri Day"},
	{"2027-12-25", "Christmas Day"},
	{"2027-12-26", "Boxing Day"},
}

// observed applies the Sunday rule: a day on a Sunday moves to the first following day that is not
// itself a holiday.
func observed(in []dated) ([]dated, error) {
	taken := map[string]bool{}
	for _, d := range in {
		taken[d.date] = true
	}
	out := make([]dated, 0, len(in))
	for _, d := range in {
		t, err := time.Parse("2006-01-02", d.date)
		if err != nil {
			return nil, fmt.Errorf("holidays: %s: %w", d.date, err)
		}
		if t.Weekday() == time.Sunday {
			for taken[t.Format("2006-01-02")] {
				t = t.AddDate(0, 0, 1)
			}
			d = dated{t.Format("2006-01-02"), d.name + " (observed)"}
			taken[d.date] = true
		}
		out = append(out, d)
	}
	return out, nil
}

// EnsurePlatform adds the national holidays to the system tenant, each once ever. It returns how
// many it added.
func EnsurePlatform(ctx context.Context, c *ent.Client, system uuid.UUID) (int, error) {
	if system == uuid.Nil {
		return 0, nil
	}
	days, err := observed(kenya)
	if err != nil {
		return 0, err
	}
	var seeded []string
	row, err := c.AppSetting.Query().Where(appsetting.TenantID(system), appsetting.AppKey(SeededKey)).Only(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return 0, fmt.Errorf("holidays: load seeded: %w", err)
	}
	if err == nil && row.Value != "" {
		if err := json.Unmarshal([]byte(row.Value), &seeded); err != nil {
			return 0, fmt.Errorf("holidays: decode seeded: %w", err)
		}
	}
	added := 0
	for _, d := range days {
		if slices.Contains(seeded, d.date) {
			continue
		}
		t, err := time.Parse("2006-01-02", d.date)
		if err != nil {
			return added, err
		}
		exists, err := c.PublicHoliday.Query().Where(publicholiday.TenantID(system), publicholiday.IsNational(true), publicholiday.Date(t)).Exist(ctx)
		if err != nil {
			return added, fmt.Errorf("holidays: check %s: %w", d.date, err)
		}
		if !exists {
			// Another replica starting at the same moment may add it first; the unique national date
			// index refuses the second, which then counts it as seeded.
			err := c.PublicHoliday.Create().SetTenantID(system).SetName(d.name).SetDate(t).SetIsNational(true).Exec(ctx)
			switch {
			case err == nil:
				added++
			case !ent.IsConstraintError(err):
				return added, fmt.Errorf("holidays: add %s: %w", d.date, err)
			}
		}
		seeded = append(seeded, d.date)
	}
	raw, err := json.Marshal(seeded)
	if err != nil {
		return added, err
	}
	err = c.AppSetting.Create().SetTenantID(system).SetAppKey(SeededKey).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).UpdateNewValues().Exec(ctx)
	if err != nil {
		return added, fmt.Errorf("holidays: save seeded: %w", err)
	}
	return added, nil
}
