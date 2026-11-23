package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AttendanceRegularisation is a request to correct one day's attendance (a missed punch, a
// wrong time). It goes through the approvals engine (module attendance_regularisation); on
// approval the record is changed and the before and after values are kept in the record's
// metadata corrections[].
type AttendanceRegularisation struct {
	ent.Schema
}

func (AttendanceRegularisation) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("record_id", uuid.UUID{}).Optional().Nillable().Comment("FK -> attendance_records.id when the day had one"),
		field.Time("date").Comment("Work day, UTC midnight"),
		field.Time("check_in").Optional().Nillable(),
		field.Time("check_out").Optional().Nillable(),
		field.Text("reason"),
		field.Enum("status").Values("pending", "approved", "rejected", "cancelled").Default("pending"),
		field.UUID("approval_request_id", uuid.UUID{}).Optional().Nillable(),
		field.JSON("before", map[string]any{}).Optional().Comment("Record check_in/check_out/status when requested"),
		field.UUID("requested_by", uuid.UUID{}).Optional().Nillable().Comment("Acting user id"),
		field.Time("decided_at").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (AttendanceRegularisation) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "employee_id", "date"),
		index.Fields("tenant_id", "status"),
	}
}
