package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AttendancePunch is one raw clock event from a device, the mobile app, the web or a manual
// entry. Punches are kept as received and paired into AttendanceRecord rows by the punch
// processor; the unique (device_sn, device_pin, punched_at) key makes a redelivered device
// batch a no-op.
type AttendancePunch struct {
	ent.Schema
}

func (AttendancePunch) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("device_id", uuid.UUID{}).Optional().Nillable().Comment("FK -> attendance_devices.id"),
		field.String("device_sn").Default("").Comment("Device serial; empty for mobile, web and manual punches"),
		field.String("device_pin").Comment("User PIN on the device, or the employee id for other sources"),
		field.UUID("employee_id", uuid.UUID{}).Optional().Nillable().Comment("Resolved from the PIN; NULL while unmatched"),
		field.Time("punched_at"),
		field.Int("status").Default(0).Comment("ZKTeco state: 0 in, 1 out, 2 break out, 3 break in, 4 OT in, 5 OT out, 255 auto"),
		field.Int("verify_mode").Default(0).Comment("ZKTeco verify type: 1 finger, 15 face, 3 password, 4 card ..."),
		field.String("work_code").Optional(),
		field.Enum("source").Values("device", "mobile", "web", "manual").Default("device"),
		field.Bool("processed").Default(false),
		field.UUID("attendance_record_id", uuid.UUID{}).Optional().Nillable(),
		field.Bool("flagged").Default(false).Comment("Outside the geo-fence, waiting for HR review"),
		// Metadata holds geo {lat, lng, accuracy_m, inside, distance_m, site_id}, photo_url and
		// the raw device line.
		field.JSON("metadata", map[string]any{}).Optional(),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (AttendancePunch) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("device_sn", "device_pin", "punched_at").Unique(),
		index.Fields("tenant_id", "punched_at"),
		index.Fields("tenant_id", "processed"),
		index.Fields("tenant_id", "employee_id", "punched_at"),
	}
}
