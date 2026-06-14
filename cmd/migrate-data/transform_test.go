package main

import (
	"database/sql"
	"testing"

	"github.com/shopspring/decimal"
)

// TestParseDecimal verifies money/decimal transform: exact (no float drift), NULL -> zero,
// and that whitespace/empty are handled. This is the gaps §2.1 "never float" guarantee.
func TestParseDecimal(t *testing.T) {
	cases := []struct {
		name string
		in   sql.NullString
		want string
	}{
		{"plain", sql.NullString{String: "12345.6789", Valid: true}, "12345.6789"},
		{"trailing-zeros", sql.NullString{String: "100.00", Valid: true}, "100"},
		{"null-is-zero", sql.NullString{Valid: false}, "0"},
		{"empty-is-zero", sql.NullString{String: "   ", Valid: true}, "0"},
		{"high-precision", sql.NullString{String: "0.0001", Valid: true}, "0.0001"},
		{"big-money", sql.NullString{String: "9999999999999.9999", Valid: true}, "9999999999999.9999"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := parseDecimal(c.in)
			want := decimal.RequireFromString(c.want)
			if !got.Equal(want) {
				t.Fatalf("parseDecimal(%v) = %s, want %s", c.in, got, want)
			}
		})
	}
}

// TestParseDecimalNoFloatDrift ensures a value that is not exactly representable in float64
// survives intact (would lose precision if we ever routed through float).
func TestParseDecimalNoFloatDrift(t *testing.T) {
	in := sql.NullString{String: "0.1", Valid: true}
	got := parseDecimal(in)
	if got.String() != "0.1" {
		t.Fatalf("decimal drift: got %s, want 0.1", got.String())
	}
}

// TestLegacyIDToUUIDDeterministic verifies the int-PK -> UUID mapping is stable across calls
// (idempotency + FK remap correctness depend on this) and namespaced per table so the same
// integer in two tables never collides.
func TestLegacyIDToUUIDDeterministic(t *testing.T) {
	a := legacyIDToUUID("employee", 42)
	b := legacyIDToUUID("employee", 42)
	if a != b {
		t.Fatalf("not deterministic: %s != %s", a, b)
	}
	// Different table, same id -> different UUID (namespacing).
	c := legacyIDToUUID("payslips", 42)
	if a == c {
		t.Fatalf("table namespacing failed: employee:42 == payslips:42 (%s)", a)
	}
	// Different id, same table -> different UUID.
	d := legacyIDToUUID("employee", 43)
	if a == d {
		t.Fatalf("id collision: employee:42 == employee:43 (%s)", a)
	}
	// Sanity: a real v5 UUID (version nibble == 5).
	if a.Version() != 5 {
		t.Fatalf("expected UUIDv5, got version %d", a.Version())
	}
}

// TestMonthAbbrevToInt covers the legacy finacial_year_start_month choices (incl. the odd
// "Sept"/"March" abbreviations Django used) and the unknown -> January default.
func TestMonthAbbrevToInt(t *testing.T) {
	cases := map[string]int{
		"Jan": 1, "Feb": 2, "March": 3, "Apr": 4, "May": 5, "Jun": 6,
		"Jul": 7, "Aug": 8, "Sept": 9, "Oct": 10, "Nov": 11, "Dec": 12,
		"december": 12, "  Jan  ": 1, "": 1, "garbage": 1,
	}
	for in, want := range cases {
		if got := monthAbbrevToInt(in); got != want {
			t.Errorf("monthAbbrevToInt(%q) = %d, want %d", in, got, want)
		}
	}
}
