package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

// Progress streams stay inside the router's 30s request timeout and the server's 20s write
// timeout: each connection streams for streamWindow and then ends; the client reconnects and
// gets the current state first, so a long run is followed across many short connections.
const (
	streamWindow = 15 * time.Second
	streamTick   = time.Second
)

func (h *PayrollHandler) registerRunRoutes(pr chi.Router) {
	pr.Get("/runs", h.ListRuns)
	pr.Get("/runs/{id}", h.GetRun)
	pr.Get("/runs/{id}/events", h.RunEvents)
}

// ListRuns returns the tenant's recent payroll runs (?limit= up to 50).
func (h *PayrollHandler) ListRuns(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	runs, err := h.svc.ListRunJobs(r.Context(), scope.TenantID, limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list payroll runs")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": runs})
}

func (h *PayrollHandler) runFromRequest(w http.ResponseWriter, r *http.Request) (RequestScope, payroll.RunJobView, bool) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return scope, payroll.RunJobView{}, false
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid run id")
		return scope, payroll.RunJobView{}, false
	}
	job, err := h.svc.GetRunJob(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "payroll run not found")
		return scope, payroll.RunJobView{}, false
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to read the payroll run")
		return scope, payroll.RunJobView{}, false
	}
	return scope, job, true
}

// GetRun returns one payroll run.
func (h *PayrollHandler) GetRun(w http.ResponseWriter, r *http.Request) {
	if _, job, ok := h.runFromRequest(w, r); ok {
		writeJSON(w, http.StatusOK, job)
	}
}

// RunEvents streams a run's progress as Server-Sent Events: a "progress" event with the run on
// connect and whenever it changes, then "done" once it is completed or failed. A connection
// lasts at most 15s; reconnect until "done". Reads are one primary-key lookup a second.
func (h *PayrollHandler) RunEvents(w http.ResponseWriter, r *http.Request) {
	scope, job, ok := h.runFromRequest(w, r)
	if !ok {
		return
	}
	rc := http.NewResponseController(w)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no") // nginx ingress: do not buffer the stream
	w.WriteHeader(http.StatusOK)

	send := func(event string, v payroll.RunJobView) bool {
		raw, _ := json.Marshal(v)
		if _, err := fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, raw); err != nil {
			return false
		}
		return rc.Flush() == nil
	}
	finish := func(v payroll.RunJobView) bool {
		if v.Finished() {
			send("done", v)
			return true
		}
		return false
	}
	if !send("progress", job) || finish(job) {
		return
	}
	last := job
	deadline := time.NewTimer(streamWindow)
	defer deadline.Stop()
	tick := time.NewTicker(streamTick)
	defer tick.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case <-deadline.C:
			// Tell the client to reconnect for more; it is not finished.
			_, _ = fmt.Fprint(w, "event: reconnect\ndata: {}\n\n")
			_ = rc.Flush()
			return
		case <-tick.C:
			cur, err := h.svc.GetRunJob(r.Context(), scope.TenantID, job.ID)
			if err != nil {
				return
			}
			if cur.Status != last.Status || cur.Done != last.Done || cur.Total != last.Total {
				if !send("progress", cur) {
					return
				}
				last = cur
			}
			if finish(cur) {
				return
			}
		}
	}
}
