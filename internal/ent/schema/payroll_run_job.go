package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PayrollRunJob is one background payroll run: queued by "process", worked by the pod that took
// it, with progress the UI streams. Any pod can serve the progress because it lives here, and a
// run whose heartbeat stops (pod killed) is marked interrupted by a sweeper on every pod.
type PayrollRunJob struct {
	ent.Schema
}

func (PayrollRunJob) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.Time("period").Comment("First day of the payroll month"),
		field.Enum("status").Values("queued", "running", "completed", "failed").Default("queued"),
		field.JSON("params", map[string]any{}).Optional().Comment("The run's filters, for display"),
		field.Int("total").Default(0).Comment("Employees in the run"),
		field.Int("done").Default(0).Comment("Employees processed so far"),
		field.Int("payslips").Default(0).Comment("Payslips written"),
		field.String("error").Optional().Nillable(),
		// "active" while queued or running, NULL once finished: with the unique index below this
		// allows one active run per tenant across every pod.
		field.String("active_lock").Optional().Nillable(),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("started_at").Optional().Nillable(),
		field.Time("finished_at").Optional().Nillable(),
		field.Time("heartbeat_at").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (PayrollRunJob) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "active_lock").Unique(),
		index.Fields("tenant_id", "created_at"),
		// The stale-run sweeper scans active runs by heartbeat.
		index.Fields("active_lock", "heartbeat_at"),
	}
}
