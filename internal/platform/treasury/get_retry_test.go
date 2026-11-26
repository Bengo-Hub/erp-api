package treasury

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"
)

// A GET retries 429 and 5xx a bounded number of times, then gives up; other errors fail at once.
func TestGetRawRetriesThenGivesUp(t *testing.T) {
	var waits []time.Duration
	waitFor = func(_ context.Context, d time.Duration) error { waits = append(waits, d); return nil }
	t.Cleanup(func() {
		waitFor = func(ctx context.Context, d time.Duration) error {
			tm := time.NewTimer(d)
			defer tm.Stop()
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-tm.C:
				return nil
			}
		}
	})
	var calls atomic.Int32
	status := http.StatusServiceUnavailable
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"cost_centers":[{"id":"` + uuid.NewString() + `","name":"Ops","is_active":true}]}`))
	}))
	defer srv.Close()
	c := NewClient(srv.URL, "key", zap.NewNop())

	if _, err := c.ListCostCenters(context.Background(), uuid.New()); err == nil {
		t.Fatal("a persistent 503 must fail")
	}
	if calls.Load() != getAttempts || len(waits) != getAttempts-1 {
		t.Errorf("calls %d waits %d, want %d and %d", calls.Load(), len(waits), getAttempts, getAttempts-1)
	}
	for _, w := range waits {
		if w <= 0 || w > getBackoffCap {
			t.Errorf("wait %s outside (0, %s]", w, getBackoffCap)
		}
	}

	calls.Store(0)
	status = http.StatusNotFound
	if _, err := c.ListCostCenters(context.Background(), uuid.New()); err == nil || calls.Load() != 1 {
		t.Errorf("a 404 must fail at once: calls %d err %v", calls.Load(), err)
	}

	calls.Store(0)
	status = http.StatusOK
	got, err := c.ListCostCenters(context.Background(), uuid.New())
	if err != nil || len(got) != 1 || got[0].Name != "Ops" || calls.Load() != 1 {
		t.Errorf("ok call: %v %v calls %d", got, err, calls.Load())
	}
}
