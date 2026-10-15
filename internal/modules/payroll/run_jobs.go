package payroll

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollrunjob"
)

// Background payroll runs. "Process" used to compute every payslip inside the HTTP request,
// which the 20s write timeout cuts off for a large payroll and which could report no progress.
// Now it queues a PayrollRunJob and returns at once; the pod that took it works the run and
// writes progress to the row, so any pod can stream it.

const (
	activeLock = "active"
	// heartbeatEvery is how often a running job proves it is alive; staleAfter is how long a
	// silent job is trusted before the sweeper marks it interrupted.
	heartbeatEvery = 15 * time.Second
	staleAfter     = 2 * time.Minute
	// maxRunTime bounds one run.
	maxRunTime = 2 * time.Hour
)

// ErrRunInProgress is returned when the tenant already has a queued or running payroll run.
var ErrRunInProgress = errors.New("payroll: a run is already in progress for this tenant")

// RunInProgressError carries the active run so the caller can point the user at it.
type RunInProgressError struct{ Job *ent.PayrollRunJob }

func (e *RunInProgressError) Error() string { return ErrRunInProgress.Error() }
func (e *RunInProgressError) Unwrap() error { return ErrRunInProgress }

// RunJobView is a run's state for the API and the progress stream.
type RunJobView struct {
	ID         uuid.UUID      `json:"id"`
	Period     string         `json:"period"` // YYYY-MM
	Status     string         `json:"status"`
	Total      int            `json:"total"`
	Done       int            `json:"done"`
	Percent    int            `json:"percent"`
	Payslips   int            `json:"payslips"`
	Error      string         `json:"error,omitempty"`
	Params     map[string]any `json:"params,omitempty"`
	CreatedBy  *uuid.UUID     `json:"created_by,omitempty"`
	StartedAt  *time.Time     `json:"started_at,omitempty"`
	FinishedAt *time.Time     `json:"finished_at,omitempty"`
	CreatedAt  time.Time      `json:"created_at"`
}

// Finished reports whether the run reached a final state.
func (v RunJobView) Finished() bool { return v.Status == "completed" || v.Status == "failed" }

func runJobView(j *ent.PayrollRunJob) RunJobView {
	v := RunJobView{
		ID: j.ID, Period: j.Period.Format("2006-01"), Status: string(j.Status), Total: j.Total, Done: j.Done,
		Payslips: j.Payslips, Params: j.Params, CreatedBy: j.CreatedBy, StartedAt: j.StartedAt,
		FinishedAt: j.FinishedAt, CreatedAt: j.CreatedAt,
	}
	if j.Error != nil {
		v.Error = *j.Error
	}
	switch {
	case j.Status == payrollrunjob.StatusCompleted:
		v.Percent = 100
	case j.Total > 0:
		v.Percent = j.Done * 100 / j.Total
	}
	return v
}

// JobRunner starts and supervises background runs on this pod.
type JobRunner struct {
	svc  *Service
	log  *zap.Logger
	base context.Context
	wg   sync.WaitGroup
	now  func() time.Time
}

// NewJobRunner returns a runner whose jobs stop when base is cancelled (server shutdown); a
// stopped job is marked interrupted so the user can run it again.
func NewJobRunner(base context.Context, svc *Service, log *zap.Logger) *JobRunner {
	if log == nil {
		log = zap.NewNop()
	}
	return &JobRunner{svc: svc, log: log, base: base, now: time.Now}
}

// Start queues a persisted run and works it in the background. One active run per tenant: a
// second request gets a *RunInProgressError naming the active one.
func (j *JobRunner) Start(ctx context.Context, p RunParams, params map[string]any) (RunJobView, error) {
	p.Persist = true
	month := time.Date(p.Period.Year(), p.Period.Month(), 1, 0, 0, 0, 0, time.UTC)
	c := j.svc.orm.PayrollRunJob.Create().
		SetTenantID(p.TenantID).SetPeriod(month).SetParams(params).SetActiveLock(activeLock).
		SetHeartbeatAt(j.now())
	if p.CreatedBy != uuid.Nil {
		c = c.SetCreatedBy(p.CreatedBy)
	}
	job, err := c.Save(ctx)
	if ent.IsConstraintError(err) {
		active, aerr := j.svc.orm.PayrollRunJob.Query().
			Where(payrollrunjob.TenantID(p.TenantID), payrollrunjob.ActiveLock(activeLock)).First(ctx)
		if aerr == nil {
			return runJobView(active), &RunInProgressError{Job: active}
		}
		return RunJobView{}, ErrRunInProgress
	}
	if err != nil {
		return RunJobView{}, fmt.Errorf("payroll: queue run: %w", err)
	}
	j.wg.Add(1)
	go j.execute(job.ID, p)
	return runJobView(job), nil
}

// Wait blocks until every job started on this pod has stopped (call after cancelling base).
func (j *JobRunner) Wait() { j.wg.Wait() }

func (j *JobRunner) execute(jobID uuid.UUID, p RunParams) {
	defer j.wg.Done()
	ctx, cancel := context.WithTimeout(j.base, maxRunTime)
	defer cancel()
	orm := j.svc.orm
	// Updates use a context that outlives a cancelled run, so the final state is always saved.
	save := func(u *ent.PayrollRunJobUpdateOne) {
		wctx, wcancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer wcancel()
		if err := u.Exec(wctx); err != nil {
			j.log.Warn("payroll run job: save state failed", zap.String("job", jobID.String()), zap.Error(err))
		}
	}
	start := j.now()
	save(orm.PayrollRunJob.UpdateOneID(jobID).SetStatus(payrollrunjob.StatusRunning).SetStartedAt(start).SetHeartbeatAt(start))

	// Progress is written at most once a second (plus the first and last), and a ticker keeps
	// the heartbeat fresh even while one employee takes long.
	var mu sync.Mutex
	var lastWrite time.Time
	progress := func(done, total int) {
		mu.Lock()
		defer mu.Unlock()
		now := j.now()
		if done != 0 && done != total && now.Sub(lastWrite) < time.Second {
			return
		}
		lastWrite = now
		save(orm.PayrollRunJob.UpdateOneID(jobID).SetDone(done).SetTotal(total).SetHeartbeatAt(now))
	}
	p.OnProgress = progress
	stopBeat := make(chan struct{})
	go func() {
		t := time.NewTicker(heartbeatEvery)
		defer t.Stop()
		for {
			select {
			case <-stopBeat:
				return
			case <-t.C:
				save(orm.PayrollRunJob.UpdateOneID(jobID).SetHeartbeatAt(j.now()))
			}
		}
	}()

	res, err := j.runSafely(ctx, p)
	close(stopBeat)

	fin := j.now()
	u := orm.PayrollRunJob.UpdateOneID(jobID).ClearActiveLock().SetFinishedAt(fin).SetHeartbeatAt(fin)
	switch {
	case err == nil:
		n := 0
		for _, l := range res {
			if l.PayslipID != nil {
				n++
			}
		}
		u = u.SetStatus(payrollrunjob.StatusCompleted).SetPayslips(n).SetDone(len(res)).SetTotal(len(res))
		j.log.Info("payroll run completed", zap.String("job", jobID.String()), zap.Int("payslips", n), zap.Duration("took", fin.Sub(start)))
	case errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded):
		u = u.SetStatus(payrollrunjob.StatusFailed).SetError("The run was interrupted (server restart or time limit). Run payroll again; payslips already written are replaced.")
		j.log.Warn("payroll run interrupted", zap.String("job", jobID.String()), zap.Error(err))
	default:
		u = u.SetStatus(payrollrunjob.StatusFailed).SetError(err.Error())
		j.log.Warn("payroll run failed", zap.String("job", jobID.String()), zap.Error(err))
	}
	save(u)
}

// runSafely turns a panic in the run into a failed job instead of a crashed pod.
func (j *JobRunner) runSafely(ctx context.Context, p RunParams) (res []LineResult, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("payroll run crashed: %v", r)
		}
	}()
	return j.svc.Run(ctx, p)
}

// SweepStale marks runs whose heartbeat stopped as interrupted and frees the tenant's lock.
// Safe on every pod: a live run heartbeats every 15s, far inside the 2 minute window.
func (j *JobRunner) SweepStale(ctx context.Context) (int, error) {
	now := j.now()
	return j.svc.orm.PayrollRunJob.Update().
		Where(payrollrunjob.ActiveLock(activeLock), payrollrunjob.HeartbeatAtLT(now.Add(-staleAfter))).
		SetStatus(payrollrunjob.StatusFailed).ClearActiveLock().SetFinishedAt(now).
		SetError("The run stopped responding (the server restarted). Run payroll again; payslips already written are replaced.").
		Save(ctx)
}

// StartSweeper sweeps once now and then every minute until base is cancelled.
func (j *JobRunner) StartSweeper() {
	sweep := func() {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if n, err := j.SweepStale(ctx); err != nil {
			j.log.Warn("payroll run sweep failed", zap.Error(err))
		} else if n > 0 {
			j.log.Warn("payroll runs marked interrupted", zap.Int("count", n))
		}
	}
	go func() {
		sweep()
		t := time.NewTicker(time.Minute)
		defer t.Stop()
		for {
			select {
			case <-j.base.Done():
				return
			case <-t.C:
				sweep()
			}
		}
	}()
}

// GetRunJob returns one of the tenant's runs.
func (s *Service) GetRunJob(ctx context.Context, tenantID, id uuid.UUID) (RunJobView, error) {
	job, err := s.orm.PayrollRunJob.Query().Where(payrollrunjob.ID(id), payrollrunjob.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return RunJobView{}, err
	}
	return runJobView(job), nil
}

// ListRunJobs returns the tenant's most recent runs, newest first (at most 50).
func (s *Service) ListRunJobs(ctx context.Context, tenantID uuid.UUID, limit int) ([]RunJobView, error) {
	if limit <= 0 || limit > 50 {
		limit = 20
	}
	rows, err := s.orm.PayrollRunJob.Query().Where(payrollrunjob.TenantID(tenantID)).
		Order(ent.Desc(payrollrunjob.FieldCreatedAt)).Limit(limit).All(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]RunJobView, len(rows))
	for i, r := range rows {
		out[i] = runJobView(r)
	}
	return out, nil
}
