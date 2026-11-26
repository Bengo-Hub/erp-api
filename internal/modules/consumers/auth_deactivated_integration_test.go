package consumers

import (
	"context"
	"testing"
	"time"

	sharedevents "github.com/Bengo-Hub/shared-events"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	"github.com/Bengo-Hub/erp-api/internal/modules/reports"
)

// A deactivated login disables the ERP user and flags the person's current employee records for
// HR on the dashboard; the employment itself (not exited, not deleted) is untouched.
func TestIntegration_AuthUserDeactivated(t *testing.T) {
	client := consumersTestClient(t)
	ctx := context.Background()
	tenant, user := uuid.New(), uuid.New()
	client.CustomUser.Create().SetID(user).SetTenantID(tenant).SetExternalID(user.String()).SetEmail("w@x.test").SaveX(ctx)
	current := client.Employee.Create().SetTenantID(tenant).SetUserID(user).SetFirstName("Wanjiru").SetEmployeeNumber("W/1").SaveX(ctx)
	left := client.Employee.Create().SetTenantID(tenant).SetUserID(user).SetFirstName("Old").SetTerminated(true).SaveX(ctx)

	c := &AuthUserSyncConsumer{log: zap.NewNop(), svc: employees.NewService(client)}
	evt := sharedevents.NewEvent("deactivated", "auth.user", user, tenant, map[string]any{"user_id": user.String(), "status": "suspended"})
	evt.Timestamp = time.Date(2026, 11, 26, 8, 0, 0, 0, time.UTC)
	if err := c.handleUserDeactivated(ctx, evt); err != nil {
		t.Fatal(err)
	}

	if client.CustomUser.GetX(ctx, user).IsActive {
		t.Error("ERP login shadow still active")
	}
	e := client.Employee.GetX(ctx, current.ID)
	if e.Terminated || e.Deleted || e.Metadata[employees.MetaLoginStatus] != "suspended" || e.Metadata[employees.MetaLoginDisabledAt] != "2026-11-26T08:00:00Z" {
		t.Errorf("current employee = terminated %v deleted %v meta %v", e.Terminated, e.Deleted, e.Metadata)
	}
	if _, flagged := client.Employee.GetX(ctx, left.ID).Metadata[employees.MetaLoginDisabledAt]; flagged {
		t.Error("an exited record was flagged")
	}

	dash, err := reports.NewService(client).HRMAnalytics(ctx, tenant, time.Now().AddDate(0, -1, 0), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if len(dash.LoginDisabled) != 1 || dash.LoginDisabled[0].EmployeeID != current.ID || dash.LoginDisabled[0].EmployeeNumber != "W/1" {
		t.Errorf("dashboard login_disabled = %+v", dash.LoginDisabled)
	}
}
