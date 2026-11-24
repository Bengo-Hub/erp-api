package handlers

import (
	"errors"
	"fmt"
	"testing"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

func TestClientMessage(t *testing.T) {
	ve := &ent.ValidationError{Name: "rule_type"}
	wrapped := fmt.Errorf("attendance: create rule: %w", ve)
	if got := clientMessage(wrapped); got != "invalid value for rule type" {
		t.Fatalf("validation error: got %q", got)
	}
	if got := clientMessage(errors.New("name is required")); got != "name is required" {
		t.Fatalf("plain error: got %q", got)
	}
}
