package treasury

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/google/uuid"
	"go.uber.org/zap"
)

func TestDisburseBatchOutcomes(t *testing.T) {
	status, body := http.StatusOK, `{"count":2,"dispatched":1,"results":[{"reference":"a","status":"dispatched"},{"reference":"b","status":"failed","error":"no account"}]}`
	var gotKey string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey = r.Header.Get("Idempotency-Key")
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()
	c := NewClient(srv.URL, "k", zap.NewNop())
	items := []Payout{{ReferenceID: "a", Amount: "1.00"}, {ReferenceID: "b", Amount: "2.00"}}

	res, err := c.DisburseBatch(context.Background(), uuid.New(), items, "batch-1")
	if err != nil || gotKey != "batch-1" {
		t.Fatalf("err = %v, key = %q", err, gotKey)
	}
	refs := res.DispatchedRefs()
	if !refs["a"] || refs["b"] {
		t.Fatalf("dispatched = %v, want only a", refs)
	}
	if err := c.Disburse(context.Background(), uuid.New(), items, "batch-1"); !errors.Is(err, ErrPartialDisburse) {
		t.Fatalf("Disburse with a failed item: err = %v, want ErrPartialDisburse", err)
	}

	// Every coded 409 maps to its own error; an uncoded one (older treasury) is a pending approval.
	conflicts := []struct {
		body string
		want error
	}{
		{`{"error":"approval_required"}`, ErrApprovalPending},
		{`{"error":"approval_required","code":"approval_required","state":"pending"}`, ErrApprovalPending},
		{`{"error":"approval_required","code":"approval_required","state":"not_submitted"}`, ErrApprovalPending},
		{`{"error":"approval_required","code":"approval_required","state":"rejected"}`, ErrApprovalRejected},
		{`{"error":"approval_required","code":"approval_required","state":"no_rule_configured"}`, ErrApprovalNotConfigured},
		{`{"error":"approval_required","code":"approval_required","blocked":[{"reference":"a","state":"pending"},{"reference":"b","state":"rejected"}]}`, ErrApprovalRejected},
		{`{"error":"no payout account","code":"no_tenant_payout_account","hint":"connect one"}`, ErrNoPayoutAccount},
		{`{"error":"duplicate request","code":"duplicate_request","message":"in flight"}`, ErrDuplicateRequest},
		{`{"error":"duplicate request","message":"in flight"}`, ErrDuplicateRequest},
	}
	for _, tc := range conflicts {
		status, body = http.StatusConflict, tc.body
		if _, err := c.DisburseBatch(context.Background(), uuid.New(), items, "batch-1"); !errors.Is(err, tc.want) {
			t.Fatalf("409 %s: err = %v, want %v", tc.body, err, tc.want)
		}
	}

	off := NewClient("", "", zap.NewNop())
	if _, err := off.DisburseBatch(context.Background(), uuid.New(), items, "k"); !errors.Is(err, ErrNotConfigured) {
		t.Fatalf("unconfigured: err = %v, want ErrNotConfigured", err)
	}
}
