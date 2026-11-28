package holidays

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/publicholiday"
)

// SeededKey is the system tenant's AppSetting listing the platform holidays already seeded, so one
// the platform owner renamed, moved or deleted does not come back on the next deploy.
const SeededKey = "holidays.seeded"

// dated is one holiday on one day; key is its rule key (empty for a holiday added by hand).
type dated struct{ date, name, key string }

// rule dates one Part I holiday in any year: a fixed month and day, or (month 0) a number of days
// from Western Easter Sunday. since is the first year it is in the Schedule (0 = always).
type rule struct {
	key, name  string
	month, day int
	easter     int
	since      int
}

// FirstYear is the first year the platform calendar is generated for.
const FirstYear = 2026

// now is the clock the calendar's horizon is taken from (a variable so tests can pin it).
var now = time.Now

// kenya is the national calendar as rules: the days in Part I of the Schedule to the Public
// Holidays Act (Cap. 110, version of 26 April 2024, https://kenyalaw.org/akn/ke/act/1912/21/eng@2024-04-26).
// The Statute Law (Miscellaneous Amendments) Act, 2024 (Act No. 3 of 2024) put Mazingira Day on
// 10 October. Section 4: "Where, in any year, a day in Part I of the Schedule falls on a Sunday,
// then the first succeeding day, not being a public holiday, shall be a public holiday and the
// first-mentioned day shall cease to be a public holiday." Good Friday and Easter Monday follow
// Western Easter Sunday.
//
// Idd-ul-Fitr (Part I) has no fixed date ("depending upon the appearance of the moon"); the
// Minister declares the day by Gazette notice, so the platform owner adds it once declared.
// Idd-ul-Azha is in Part II (for persons of the Islamic faith) and Diwali in Part III (Hindu faith);
// either is national only in a year a Gazette notice under section 3 makes it so.
//
// The calendar is generated from rules for every year from FirstYear to next year, so it never runs
// out and the whole current year is there (it used to start at December 2026). The keys match the
// notifications-api occasions that greet customers on these days, which read the dates from here.
var kenya = []rule{
	{key: "new_year", name: "New Year's Day", month: 1, day: 1},
	{key: "good_friday", name: "Good Friday", easter: -2},
	{key: "easter_monday", name: "Easter Monday", easter: 1},
	{key: "labour_day", name: "Labour Day", month: 5, day: 1},
	{key: "madaraka_day", name: "Madaraka Day", month: 6, day: 1},
	{key: "mazingira_day", name: "Mazingira Day", month: 10, day: 10, since: 2024},
	{key: "mashujaa_day", name: "Mashujaa Day", month: 10, day: 20},
	{key: "jamhuri_day", name: "Jamhuri Day", month: 12, day: 12},
	{key: "christmas", name: "Christmas Day", month: 12, day: 25},
	{key: "boxing_day", name: "Boxing Day", month: 12, day: 26},
}

// gazetted are the keys of the days the platform owner adds by hand once the Kenya Gazette
// declares them, by name; notifications-api dates its Idd greetings from them.
var gazetted = map[string]string{"idd ul fitr": "idd_ul_fitr", "idd ul azha": "idd_ul_azha", "idd ul adha": "idd_ul_azha"}

// KeyOf is the key of a platform holiday by its name, with "(observed)", capitals and hyphens
// ignored; empty for a name that is neither a rule nor a gazetted day.
func KeyOf(name string) string {
	norm := func(s string) string {
		s = strings.TrimSuffix(strings.TrimSpace(strings.ToLower(s)), "(observed)")
		return strings.Join(strings.Fields(strings.ReplaceAll(s, "-", " ")), " ")
	}
	name = norm(name)
	for _, r := range kenya {
		if norm(r.name) == name {
			return r.key
		}
	}
	return gazetted[name]
}

// easterSunday is Western (Gregorian) Easter Sunday, by the anonymous Gregorian algorithm.
func easterSunday(year int) time.Time {
	a := year % 19
	b, c := year/100, year%100
	d, e := b/4, b%4
	f := (b + 8) / 25
	g := (b - f + 1) / 3
	h := (19*a + b - d - g + 15) % 30
	i, k := c/4, c%4
	l := (32 + 2*e + 2*i - h - k) % 7
	m := (a + 11*h + 22*l) / 451
	month := (h + l - 7*m + 114) / 31
	day := (h+l-7*m+114)%31 + 1
	return time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)
}

// calendar is the Part I holidays of the years from..to, in date order, before the Sunday rule.
func calendar(from, to int) []dated {
	var out []dated
	for y := from; y <= to; y++ {
		for _, r := range kenya {
			if r.since > y {
				continue
			}
			t := time.Date(y, time.Month(r.month), r.day, 0, 0, 0, 0, time.UTC)
			if r.month == 0 {
				t = easterSunday(y).AddDate(0, 0, r.easter)
			}
			out = append(out, dated{t.Format("2006-01-02"), r.name, r.key})
		}
	}
	slices.SortStableFunc(out, func(a, b dated) int { return strings.Compare(a.date, b.date) })
	return out
}

// horizon is the last year the platform calendar is kept for: next year, so next year's leave can
// be planned now.
func horizon() int { return now().Year() + 1 }

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
			d = dated{t.Format("2006-01-02"), d.name + " (observed)", d.key}
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
	days, err := observed(calendar(FirstYear, horizon()))
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
