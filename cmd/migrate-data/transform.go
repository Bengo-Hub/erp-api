package main

import (
	"database/sql"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// nairobi is the IANA zone the legacy Django app stored datetimes against (USE_TZ=True,
// TIME_ZONE=Africa/Nairobi). Datetimes are normalized to this zone on read so date-only
// fields land on the correct calendar day.
var nairobi = mustLoadNairobi()

func mustLoadNairobi() *time.Location {
	loc, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		// Fallback to a fixed +03:00 offset if the tzdata is unavailable on the host.
		return time.FixedZone("EAT", 3*60*60)
	}
	return loc
}

// monthAbbrevToInt converts the legacy Bussiness.finacial_year_start_month choice
// (e.g. "Jan", "Sept", "March") to a 1-12 month number. Defaults to 1 (January) for
// unknown/empty values so company_settings always has a valid financial year start.
func monthAbbrevToInt(s string) int {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "jan", "january":
		return 1
	case "feb", "february":
		return 2
	case "march", "mar":
		return 3
	case "apr", "april":
		return 4
	case "may":
		return 5
	case "jun", "june":
		return 6
	case "jul", "july":
		return 7
	case "aug", "august":
		return 8
	case "sept", "sep", "september":
		return 9
	case "oct", "october":
		return 10
	case "nov", "november":
		return 11
	case "dec", "december":
		return 12
	default:
		return 1
	}
}

// legacyIDToUUID deterministically derives a stable UUID for a legacy Django integer PK
// within a given table namespace. It is a UUIDv5 (name-based) over "<table>:<id>" so the
// same legacy row always maps to the same UUID — this is what makes the migrator idempotent
// even for tables whose Ent schema has no natural unique key and no legacy_id column. FK
// remap then derives the parent's UUID with the same function instead of a lookup table.
//
// NOTE: the project standard for *new* rows is UUIDv7; for migrated rows we deliberately use
// a deterministic v5 so re-runs and FK remaps are reproducible without a side table.
func legacyIDToUUID(table string, id int64) uuid.UUID {
	return uuid.NewSHA1(migrationNamespace, []byte(table+":"+itoa(id)))
}

// migrationNamespace is a fixed namespace UUID for all erp-api data-migration v5 IDs.
// Changing it would change every derived ID, so it must remain constant forever.
var migrationNamespace = uuid.MustParse("b6f2c1e0-2a4d-5f7b-9c8e-1d3a5b7c9e10")

func itoa(i int64) string {
	return strconv.FormatInt(i, 10)
}

// parseDecimal converts a nullable SQL numeric/string into a shopspring decimal, returning
// decimal.Zero for NULL. It NEVER goes through float64 (gaps §2.1 — decimal money is exact).
func parseDecimal(v sql.NullString) decimal.Decimal {
	if !v.Valid || strings.TrimSpace(v.String) == "" {
		return decimal.Zero
	}
	d, err := decimal.NewFromString(strings.TrimSpace(v.String))
	if err != nil {
		return decimal.Zero
	}
	return d
}

// parseDecimalPtr is the nullable variant: NULL -> nil, otherwise a *decimal.
func parseDecimalPtr(v sql.NullString) *decimal.Decimal {
	if !v.Valid || strings.TrimSpace(v.String) == "" {
		return nil
	}
	d, err := decimal.NewFromString(strings.TrimSpace(v.String))
	if err != nil {
		return nil
	}
	return &d
}

// nairobiTime normalizes a nullable timestamp to the Africa/Nairobi calendar.
func nairobiTime(v sql.NullTime) *time.Time {
	if !v.Valid {
		return nil
	}
	t := v.Time.In(nairobi)
	return &t
}

// strOrEmpty returns the string value or "" for NULL.
func strOrEmpty(v sql.NullString) string {
	if !v.Valid {
		return ""
	}
	return v.String
}

// strPtr returns a *string or nil for NULL/empty.
func strPtr(v sql.NullString) *string {
	if !v.Valid || v.String == "" {
		return nil
	}
	s := v.String
	return &s
}

// uuidFromNull parses a nullable uuid column (e.g. business_details.tenant_id, employee.outlet_id).
func uuidFromNull(v sql.NullString) (uuid.UUID, bool) {
	if !v.Valid || v.String == "" {
		return uuid.Nil, false
	}
	id, err := uuid.Parse(v.String)
	if err != nil {
		return uuid.Nil, false
	}
	return id, true
}

// boolOr returns the bool value or the supplied default for NULL.
func boolOr(v sql.NullBool, def bool) bool {
	if !v.Valid {
		return def
	}
	return v.Bool
}
