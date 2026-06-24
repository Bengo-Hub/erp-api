package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// writeJSON writes the payload as a JSON response with the given status code.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// respondJSON is an alias kept for health.go compatibility.
func respondJSON(w http.ResponseWriter, status int, data interface{}) {
	writeJSON(w, status, data)
}

type errorResponse struct {
	Error   string `json:"error"`
	Code    string `json:"code,omitempty"`
	Details string `json:"details,omitempty"`
}

// writeError writes a structured JSON error response.
func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, errorResponse{Error: message, Code: code})
}

// writePaginated writes a list response using the shared pagination envelope
// (data/total/limit/page/hasMore). It is used by handlers whose service layer
// already returns a (slice, total) pair from an offset/limit query.
func writePaginated[T any](w http.ResponseWriter, rows []T, total int, p pagination.Params) {
	writeJSON(w, http.StatusOK, pagination.NewResponse(rows, total, p))
}

// writePagedSlice writes a list response for handlers whose service layer returns
// the full result set (no DB-level paging). It slices the in-memory rows to the
// requested page and reports the true total, so every list endpoint shares the
// uniform pagination envelope without requiring service/schema changes.
func writePagedSlice[T any](w http.ResponseWriter, rows []T, p pagination.Params) {
	total := len(rows)
	start := p.Offset
	if start > total {
		start = total
	}
	end := start + p.Limit
	if end > total {
		end = total
	}
	writeJSON(w, http.StatusOK, pagination.NewResponse(rows[start:end], total, p))
}

// parseDecimalDefault parses a decimal string, returning decimal.Zero for an empty value.
func parseDecimalDefault(s string) (decimal.Decimal, error) {
	if s == "" {
		return decimal.Zero, nil
	}
	return decimal.NewFromString(s)
}

// parseRequiredDecimal parses a money/rate field that MUST be present and a valid, non-negative
// number. Unlike parseDecimalDefault (which silently coerces a parse error to zero), this
// surfaces a validation error so callers can return a 400 instead of persisting a silent zero.
func parseRequiredDecimal(s, field string) (decimal.Decimal, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return decimal.Zero, fmt.Errorf("%s is required", field)
	}
	d, err := decimal.NewFromString(s)
	if err != nil {
		return decimal.Zero, fmt.Errorf("%s must be a valid number", field)
	}
	if d.IsNegative() {
		return decimal.Zero, fmt.Errorf("%s must not be negative", field)
	}
	return d, nil
}

// parsePositiveDecimal is parseRequiredDecimal plus a strictly-greater-than-zero check.
func parsePositiveDecimal(s, field string) (decimal.Decimal, error) {
	d, err := parseRequiredDecimal(s, field)
	if err != nil {
		return decimal.Zero, err
	}
	if !d.IsPositive() {
		return decimal.Zero, fmt.Errorf("%s must be greater than zero", field)
	}
	return d, nil
}

// validateDateOrder ensures end is not before start when both are present (YYYY-MM-DD/RFC3339).
// Empty values are skipped (the field is optional at this layer).
func validateDateOrder(startStr, endStr string) error {
	if startStr == "" || endStr == "" {
		return nil
	}
	start, err := parseDate(startStr)
	if err != nil {
		return fmt.Errorf("invalid start date")
	}
	end, err := parseDate(endStr)
	if err != nil {
		return fmt.Errorf("invalid end date")
	}
	if end.Before(start) {
		return fmt.Errorf("end date must not be before start date")
	}
	return nil
}

// parseDate parses a YYYY-MM-DD (or RFC3339) date string to a UTC time.
func parseDate(s string) (time.Time, error) {
	if s == "" {
		return time.Time{}, errEmptyDate
	}
	if t, err := time.Parse("2006-01-02", s); err == nil {
		return t.UTC(), nil
	}
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		return time.Time{}, err
	}
	return t.UTC(), nil
}

var errEmptyDate = &dateError{}

type dateError struct{}

func (*dateError) Error() string { return "empty date" }

// optionalUUIDParam parses a query param as a UUID, returning nil when absent/invalid.
func optionalUUIDParam(r *http.Request, key string) *uuid.UUID {
	v := r.URL.Query().Get(key)
	if v == "" {
		return nil
	}
	id, err := uuid.Parse(v)
	if err != nil {
		return nil
	}
	return &id
}

// appendUniqueStr appends s to slice only if not already present.
func appendUniqueStr(slice []string, s string) []string {
	for _, v := range slice {
		if v == s {
			return slice
		}
	}
	return append(slice, s)
}
