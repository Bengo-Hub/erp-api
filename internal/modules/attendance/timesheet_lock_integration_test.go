package attendance

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/timesheetentry"
)

// Concurrent timer stops for the same day, project and no task (NULL, which the unique index cannot
// compare) must end as one entry holding every hour: the timesheet lock queues them, so none is lost
// and no twin entry appears.
func TestIntegration_ConcurrentAddsShareOneEntry(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	svc := NewService(client)
	tenant, employee, project := uuid.New(), uuid.New(), uuid.New()
	day := func(s string) time.Time { d, _ := time.Parse(time.DateOnly, s); return d }

	// Open the week first, so every call below writes to the same timesheet.
	first, err := svc.LogEmployeeEntry(ctx, tenant, EmployeeEntryInput{
		EmployeeID: employee, PeriodStart: day("2026-11-16"), PeriodEnd: day("2026-11-22"),
		Date: day("2026-11-17"), ProjectID: &project, Hours: decimal.NewFromInt(1), Add: true,
	})
	if err != nil {
		t.Fatal(err)
	}

	const adds = 8
	var wg sync.WaitGroup
	errs := make(chan error, adds)
	for i := 0; i < adds; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := svc.LogEmployeeEntry(ctx, tenant, EmployeeEntryInput{
				EmployeeID: employee, PeriodStart: day("2026-11-16"), PeriodEnd: day("2026-11-22"),
				Date: day("2026-11-17"), ProjectID: &project, Hours: decimal.RequireFromString("0.5"), Add: true,
			})
			errs <- err
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatalf("concurrent add: %v", err)
		}
	}

	rows, err := client.TimesheetEntry.Query().Where(
		timesheetentry.TenantID(tenant), timesheetentry.TimesheetID(first.Timesheet.ID),
	).All(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 {
		t.Fatalf("entries = %d, want one entry for the day, project and no task", len(rows))
	}
	if want := decimal.RequireFromString("5"); !rows[0].RegularHours.Equal(want) {
		t.Fatalf("hours = %s, want %s (1 + 8 x 0.5)", rows[0].RegularHours, want)
	}
	ts, err := svc.getTimesheet(ctx, tenant, first.Timesheet.ID)
	if err != nil {
		t.Fatal(err)
	}
	if !ts.TotalHours.Equal(decimal.RequireFromString("5")) {
		t.Fatalf("timesheet total = %s, want 5", ts.TotalHours)
	}
}
