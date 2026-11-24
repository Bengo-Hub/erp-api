package handlers

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
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

// clientMessage turns a service error into text safe to show a user: an Ent validator failure
// becomes "invalid value for <field>" instead of the raw "ent: validator failed..." chain.
func clientMessage(err error) string {
	var ve *ent.ValidationError
	if errors.As(err, &ve) {
		return "invalid value for " + strings.ReplaceAll(ve.Name, "_", " ")
	}
	if ent.IsConstraintError(err) {
		for index, msg := range uniqueViolationMessages {
			if strings.Contains(err.Error(), index) {
				return msg
			}
		}
	}
	return err.Error()
}

// uniqueViolationMessages maps a unique index name to the message a user sees when a save breaks it.
var uniqueViolationMessages = map[string]string{
	"employee_tenant_id_national_id":                "Another employee already has this national ID",
	"employee_tenant_id_device_pin":                 "Another employee already uses this device PIN",
	"publicholiday_tenant_id_date_county":           "A holiday for this county already falls on that date",
	"staffshiftoverride_tenant_id_employee_id_date": "This employee already has a shift override on that date",
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
	page, total := pageWindow(rows, p)
	writeJSON(w, http.StatusOK, pagination.NewResponse(page, total, p))
}

// pageWindow slices in-memory rows to the requested page and returns the full count, for
// handlers that decorate only the visible page (names, shift hours) before writing it.
func pageWindow[T any](rows []T, p pagination.Params) ([]T, int) {
	total := len(rows)
	start := p.Offset
	if start > total {
		start = total
	}
	end := start + p.Limit
	if end > total {
		end = total
	}
	return rows[start:end], total
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

// optionalBoolParam reads the first of the given query keys that is set as a bool (true/false,
// 1/0), returning nil when none is set or the value is not a bool.
func optionalBoolParam(r *http.Request, keys ...string) *bool {
	for _, key := range keys {
		v := r.URL.Query().Get(key)
		if v == "" {
			continue
		}
		b, err := strconv.ParseBool(v)
		if err != nil {
			return nil
		}
		return &b
	}
	return nil
}

// optionalUUIDString parses a body string as a UUID, returning nil when empty or invalid.
func optionalUUIDString(v string) *uuid.UUID {
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
