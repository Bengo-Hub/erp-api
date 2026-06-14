package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ESSSettings is per-tenant Employee Self-Service configuration (legacy
// hrm.attendance.ESSSettings — was a global singleton; now one row per tenant, fixing the
// no-isolation gap). Unique on tenant_id.
type ESSSettings struct {
	ent.Schema
}

func (ESSSettings) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Unique().Comment("Owning tenant (one settings row per tenant)"),
		field.Bool("enable_shift_based_restrictions").Default(true),
		field.Bool("allow_payslip_view").Default(true),
		field.Bool("allow_leave_application").Default(true),
		field.Bool("allow_timesheet_application").Default(false),
		field.Bool("allow_overtime_application").Default(false),
		field.Bool("allow_advance_salary_application").Default(false),
		field.Bool("allow_losses_damage_submission").Default(false),
		field.Bool("allow_expense_claims_application").Default(false),
		field.Bool("require_password_change_on_first_login").Default(true),
		field.Int("session_timeout_minutes").Default(60),
		field.Bool("allow_weekend_login").Default(false),
		field.Int("max_failed_login_attempts").Default(5),
		field.Int("account_lockout_duration_minutes").Default(30),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ESSSettings) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id").Unique(),
	}
}
