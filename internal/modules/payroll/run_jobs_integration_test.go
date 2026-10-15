package payroll

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/payrollrunjob"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

func TestIntegration_PayrollRunJobs(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	// No statutory formulas are configured, so the run fails loud: the job must record the
	// failure and free the tenant's lock.
	svc := NewService(client, payrollsettings.NewService(client, uuid.New()))
	base, stop := context.WithCancel(context.Background())
	defer stop()
	runner := NewJobRunner(base, svc, nil)
	sep := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)
	client.Employee.Create().SetTenantID(tenant).SetFirstName("A").SaveX(ctx)

	job, err := runner.Start(ctx, RunParams{TenantID: tenant, Period: sep, CreatedBy: uuid.New()}, map[string]any{"payment_period": "2026-09"})
	if err != nil {
		t.Fatal(err)
	}
	runner.Wait()
	got, err := svc.GetRunJob(ctx, tenant, job.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != "failed" || got.Error == "" || got.FinishedAt == nil || got.Period != "2026-09" || got.Params["payment_period"] != "2026-09" {
		t.Fatalf("failed run = %+v, want failed with the reason", got)
	}
	if row := client.PayrollRunJob.GetX(ctx, job.ID); row.ActiveLock != nil {
		t.Fatal("a finished run must release the tenant lock")
	}

	// One active run per tenant: while one is active a second start names it.
	active := client.PayrollRunJob.Create().SetTenantID(tenant).SetPeriod(sep).SetActiveLock(activeLock).
		SetStatus(payrollrunjob.StatusRunning).SetHeartbeatAt(time.Now()).SaveX(ctx)
	_, err = runner.Start(ctx, RunParams{TenantID: tenant, Period: sep}, nil)
	var busy *RunInProgressError
	if !errors.As(err, &busy) || busy.Job.ID != active.ID || !errors.Is(err, ErrRunInProgress) {
		t.Fatalf("second start = %v, want a RunInProgressError naming %s", err, active.ID)
	}
	// Another tenant is not blocked.
	other := uuid.New()
	if _, err := runner.Start(ctx, RunParams{TenantID: other, Period: sep}, nil); err != nil {
		t.Fatalf("another tenant was blocked: %v", err)
	}
	runner.Wait()

	// The sweeper leaves a fresh heartbeat alone and interrupts a silent run.
	if n, err := runner.SweepStale(ctx); err != nil || n != 0 {
		t.Fatalf("sweep with a live run = %d, %v", n, err)
	}
	client.PayrollRunJob.UpdateOneID(active.ID).SetHeartbeatAt(time.Now().Add(-5 * time.Minute)).ExecX(ctx)
	if n, err := runner.SweepStale(ctx); err != nil || n != 1 {
		t.Fatalf("sweep with a stale run = %d, %v", n, err)
	}
	swept := client.PayrollRunJob.GetX(ctx, active.ID)
	if swept.Status != payrollrunjob.StatusFailed || swept.ActiveLock != nil || swept.Error == nil {
		t.Fatalf("swept run = %+v", swept)
	}

	// Runs list newest first, scoped to the tenant.
	runs, err := svc.ListRunJobs(ctx, tenant, 10)
	if err != nil || len(runs) != 2 || runs[0].ID != active.ID {
		t.Fatalf("runs = %+v %v", runs, err)
	}
	if _, err := svc.GetRunJob(ctx, other, active.ID); err == nil {
		t.Fatal("another tenant must not read the run")
	}
}

func TestIntegration_PayrollRunJobInterruptedOnShutdown(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	svc := NewService(client, payrollsettings.NewService(client, uuid.New()))
	base, stop := context.WithCancel(context.Background())
	runner := NewJobRunner(base, svc, nil)
	stop() // the server is already shutting down when the run starts
	job, err := runner.Start(ctx, RunParams{TenantID: tenant, Period: time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)}, nil)
	if err != nil {
		t.Fatal(err)
	}
	runner.Wait()
	row := client.PayrollRunJob.GetX(ctx, job.ID)
	if row.Status != payrollrunjob.StatusFailed || row.ActiveLock != nil || row.Error == nil {
		t.Fatalf("run on a stopping server = %+v, want failed (interrupted) with the lock released", row)
	}
}
