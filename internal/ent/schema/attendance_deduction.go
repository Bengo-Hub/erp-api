package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AttendanceDeduction is one employee's pay deduction for a month's lateness or unexcused
// absence, computed from attendance records and the tenant's attendance rules. It is reviewed
// before it reaches a payslip: HR approves or waives each row, and only approved rows are
// deducted (as unpaid time, before statutory deductions and PAYE). The payroll run marks them
// applied with the payslip they went into.
type AttendanceDeduction struct {
	ent.Schema
}

func (AttendanceDeduction) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.Time("period").Comment("First day of the payroll month"),
		field.Enum("kind").Values("late", "absence"),
		field.Int("occurrences").Default(0).Comment("Late arrivals or unexcused absent days counted"),
		field.Int("minutes").Default(0).Comment("Total minutes late (late rows)"),
		moneyField("amount"),
		field.String("basis").Comment("How the amount was worked out, shown to the reviewer"),
		field.UUID("rule_id", uuid.UUID{}).Optional().Nillable().Comment("The attendance rule applied"),
		field.Enum("status").Values("pending", "approved", "waived", "applied").Default("pending"),
		field.UUID("reviewed_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("reviewed_at").Optional().Nillable(),
		field.String("note").Optional().Nillable().Comment("Reviewer's note, e.g. why it was waived"),
		field.UUID("payslip_id", uuid.UUID{}).Optional().Nillable().Comment("Set when applied"),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (AttendanceDeduction) Indexes() []ent.Index {
	return []ent.Index{
		// One row per employee, month and kind: recomputing replaces a pending row in place.
		index.Fields("tenant_id", "employee_id", "period", "kind").Unique(),
		// The review list and the payroll run read a month by status.
		index.Fields("tenant_id", "period", "status"),
	}
}
