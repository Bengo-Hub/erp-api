package employees

import (
	"context"
	"database/sql"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/outboxevent"
)

// Creating an employee and changing a shared field each write one erp.employee.upserted row in
// the same transaction; other edits write none, and a rolled-back change leaves nothing behind.
func TestIntegration_EmployeeUpsertedEvent(t *testing.T) {
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_empev_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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
	ctx := context.Background()
	if err := client.Schema.Create(ctx); err != nil {
		t.Fatal(err)
	}
	client.Employee.Use(UpsertedEventHook("erp"))
	events := func() int {
		return client.OutboxEvent.Query().Where(outboxevent.EventType(EventEmployeeUpserted)).CountX(ctx)
	}

	tenant := uuid.New()
	e := client.Employee.Create().SetTenantID(tenant).SetFirstName("Amina").SetEmployeeNumber("A/1").SaveX(ctx)
	if events() != 1 {
		t.Fatalf("after create: %d events, want 1", events())
	}
	e = e.Update().SetGender("female").SaveX(ctx)
	if events() != 1 {
		t.Errorf("an unshared field published an event")
	}
	e = e.Update().SetEmployeeNumber("A/2").SaveX(ctx)
	if events() != 2 {
		t.Errorf("staff number change: %d events, want 2", events())
	}
	row := client.OutboxEvent.Query().Where(outboxevent.EventType(EventEmployeeUpserted)).
		Order(ent.Desc(outboxevent.FieldCreatedAt)).FirstX(ctx)
	var env struct {
		Payload map[string]any `json:"payload"`
	}
	_ = json.Unmarshal(row.Payload, &env)
	if env.Payload["employee_number"] != "A/2" || row.AggregateType != "erp" {
		t.Errorf("payload %s aggregate %s", row.Payload, row.AggregateType)
	}

	tx, err := client.Tx(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := tx.Employee.UpdateOneID(e.ID).SetFirstName("Rolled").Save(ctx); err != nil {
		t.Fatal(err)
	}
	_ = tx.Rollback()
	if events() != 2 {
		t.Errorf("a rolled-back change left an event")
	}
}
