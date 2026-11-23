package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AttendanceDevice is a biometric terminal (ZKTeco PUSH/ADMS) registered by a tenant. The
// device reaches the cloud with only its serial number, so the serial is unique across all
// tenants and is how the public /iclock endpoints find the owning tenant.
type AttendanceDevice struct {
	ent.Schema
}

func (AttendanceDevice) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("outlet_id", uuid.UUID{}).Optional().Nillable().Comment("Auth outlet the device sits in"),
		field.UUID("work_site_id", uuid.UUID{}).Optional().Nillable().Comment("FK -> work_sites.id"),
		field.String("serial_number").NotEmpty().Comment("Device serial (SN) sent on every push"),
		field.String("name"),
		field.Enum("mode").Values("ta", "ac").Default("ta").Comment("ta = time attendance push, ac = access control push"),
		field.Bool("active").Default(true),
		field.String("timezone").Optional().Comment("IANA zone; empty means the tenant zone"),
		field.Time("last_seen_at").Optional().Nillable(),
		field.String("firmware").Optional(),
		field.String("push_version").Optional(),
		field.String("last_ip").Optional(),
		field.Int("user_count").Default(0),
		field.Int("punch_count").Default(0).Comment("Attendance log count the device last reported"),
		// Metadata holds the comm key, ATTLOG/OPERLOG stamps and option overrides.
		field.JSON("metadata", map[string]any{}).Optional(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (AttendanceDevice) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		// Global on purpose: the serial alone identifies the tenant on the public endpoints.
		index.Fields("serial_number").Unique(),
	}
}
