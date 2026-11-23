package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// DeviceCommand is a queued command for a biometric device. The device collects it on its
// next /iclock/getrequest poll as "C:<cmd_no>:<command>" and reports the outcome to
// /iclock/devicecmd, which closes the row.
type DeviceCommand struct {
	ent.Schema
}

func (DeviceCommand) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("device_id", uuid.UUID{}).Comment("FK -> attendance_devices.id"),
		field.Int64("cmd_no").Comment("Numeric id echoed by the device, unique per device"),
		field.String("command_type").Comment("sync_users | open_door | reboot | reload_logs | clear_logs"),
		field.Text("command").Comment("Protocol line(s) sent to the device"),
		field.Enum("status").Values("queued", "sent", "done", "failed").Default("queued"),
		field.Int("return_code").Optional().Nillable(),
		field.Text("result").Optional(),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("sent_at").Optional().Nillable(),
		field.Time("completed_at").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (DeviceCommand) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("device_id", "status"),
		index.Fields("device_id", "cmd_no").Unique(),
	}
}
