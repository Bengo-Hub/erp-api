package handlers

import (
	"bufio"
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"go.uber.org/zap"

	authclient "github.com/Bengo-Hub/shared-auth-client"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollrunjob"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

func handlersTestClient(t *testing.T) *ent.Client {
	t.Helper()
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_h_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	if _, err := admin.Exec("CREATE SCHEMA " + schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = admin.Exec("DROP SCHEMA " + schema + " CASCADE"); _ = admin.Close() })
	sep := "?"
	if strings.Contains(url, "?") {
		sep = "&"
	}
	db, err := sql.Open("pgx", url+sep+"search_path="+schema)
	if err != nil {
		t.Fatal(err)
	}
	client := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, db)))
	t.Cleanup(func() { _ = client.Close() })
	if err := client.Schema.Create(context.Background()); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return client
}

func TestRunEventsStreamsUntilDone(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	job := client.PayrollRunJob.Create().SetTenantID(tenant).SetPeriod(time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)).
		SetStatus(payrollrunjob.StatusRunning).SetTotal(4).SetDone(1).SetActiveLock("active").SaveX(ctx)

	h := NewPayrollHandler(zap.NewNop(), payroll.NewService(client, nil), nil)
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			claims := &authclient.Claims{TenantID: tenant.String(), IsPlatformOwner: true}
			next.ServeHTTP(w, req.WithContext(authclient.ContextWithClaims(req.Context(), claims)))
		})
	})
	h.RegisterRoutes(r)
	srv := httptest.NewServer(r)
	defer srv.Close()

	// Finish the run while the stream is open.
	go func() {
		time.Sleep(1500 * time.Millisecond)
		client.PayrollRunJob.UpdateOneID(job.ID).SetStatus(payrollrunjob.StatusCompleted).SetDone(4).
			SetPayslips(4).ClearActiveLock().ExecX(context.Background())
	}()
	began := time.Now()
	resp, err := http.Get(srv.URL + "/hrm/payroll/runs/" + job.ID.String() + "/events")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if ct := resp.Header.Get("Content-Type"); ct != "text/event-stream" || resp.Header.Get("X-Accel-Buffering") != "no" {
		t.Fatalf("headers: %v", resp.Header)
	}
	var events []string
	var last payroll.RunJobView
	sc := bufio.NewScanner(resp.Body)
	event := ""
	for sc.Scan() {
		line := sc.Text()
		switch {
		case strings.HasPrefix(line, "event: "):
			event = strings.TrimPrefix(line, "event: ")
			events = append(events, event)
		case strings.HasPrefix(line, "data: ") && event != "reconnect":
			if err := json.Unmarshal([]byte(strings.TrimPrefix(line, "data: ")), &last); err != nil {
				t.Fatalf("bad data %q: %v", line, err)
			}
		}
	}
	// The stream ends as soon as the run finishes, not at the end of its window.
	if took := time.Since(began); took > 8*time.Second {
		t.Errorf("stream took %s to end after the run finished", took)
	}
	if len(events) < 2 || events[0] != "progress" || events[len(events)-1] != "done" {
		t.Fatalf("events = %v, want progress first and done last", events)
	}
	if last.Status != "completed" || last.Percent != 100 || last.Payslips != 4 {
		t.Fatalf("final state = %+v", last)
	}

	// The poller envelope reads the same run.
	resp2, err := http.Get(srv.URL + "/hrm/payroll/task_status?task_id=" + job.ID.String())
	if err != nil {
		t.Fatal(err)
	}
	defer resp2.Body.Close()
	var env map[string]any
	_ = json.NewDecoder(resp2.Body).Decode(&env)
	if env["state"] != "SUCCESS" || env["progress"] != float64(100) {
		t.Fatalf("task_status = %v", env)
	}

	// Another tenant's run is not found.
	foreign := client.PayrollRunJob.Create().SetTenantID(uuid.New()).SetPeriod(time.Now()).SaveX(ctx)
	resp3, err := http.Get(srv.URL + "/hrm/payroll/runs/" + foreign.ID.String())
	if err != nil {
		t.Fatal(err)
	}
	resp3.Body.Close()
	if resp3.StatusCode != http.StatusNotFound {
		t.Fatalf("foreign run status = %d, want 404", resp3.StatusCode)
	}
}
