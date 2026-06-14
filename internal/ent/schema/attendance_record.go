package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// AttendanceRecord is a daily attendance row (legacy hrm.attendance.AttendanceRecord).
// Tenant-scoped; unique per (tenant, employee, date). GPS/biometric capture preserved;
// regular/overtime hours are decimal and computed from AttendanceRule on check-out.
type AttendanceRecord struct {
	ent.Schema
}

func (AttendanceRecord) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("outlet_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("work_shift_id", uuid.UUID{}).Optional().Nillable().Comment("FK -> work_shifts.id"),
		field.Time("date"),
		field.Time("check_in").Optional().Nillable(),
		field.Time("check_out").Optional().Nillable(),
		field.String("biometric_id").Optional().Nillable().Comment("Biometric device/user ID"),
		field.Other("gps_latitude", decimal.Decimal{}).
			SchemaType(map[string]string{"postgres": "numeric(9,6)"}).Optional().Nillable(),
		field.Other("gps_longitude", decimal.Decimal{}).
			SchemaType(map[string]string{"postgres": "numeric(9,6)"}).Optional().Nillable(),
		field.Enum("status").Values("present", "absent", "late", "half-day").Default("present"),
		field.Int("total_seconds_worked").Default(0),
		hoursField("regular_hours"),
		hoursField("overtime_hours"),
		field.String("notes").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (AttendanceRecord) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id", "date").Unique(),
		index.Fields("tenant_id", "date"),
		index.Fields("tenant_id", "status"),
	}
}
