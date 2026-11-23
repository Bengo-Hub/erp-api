package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// OvertimeRequest asks for overtime on a day, before or after it is worked. It goes through
// the approvals engine (module overtime_request). When the tenant requires overtime approval,
// payroll pays at most the approved hours for the day.
type OvertimeRequest struct {
	ent.Schema
}

func (OvertimeRequest) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.Time("date").Comment("Work day, UTC midnight"),
		hoursField("hours"),
		field.Text("reason").Optional(),
		field.Enum("status").Values("pending", "approved", "rejected", "cancelled").Default("pending"),
		field.UUID("approval_request_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("requested_by", uuid.UUID{}).Optional().Nillable().Comment("Acting user id"),
		field.Time("decided_at").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (OvertimeRequest) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "employee_id", "date"),
		index.Fields("tenant_id", "status"),
	}
}
