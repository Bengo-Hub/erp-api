package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Employee is the HR FK hub (legacy hrm.employees.Employee). Tenant + outlet scoped
//. Identity (user) lives in auth-api; this row references the
// SSO user shadow by user_id and stores HR/statutory attributes.
type Employee struct {
	ent.Schema
}

func (Employee) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id) — REQUIRED for isolation"),
		field.UUID("outlet_id", uuid.UUID{}).Optional().Nillable().
			Comment("Auth-api outlet UUID for HR outlet scoping (X-Outlet-ID)"),
		field.UUID("user_id", uuid.UUID{}).Optional().Nillable().
			Comment("CustomUser shadow id (SSO/ESS link)"),

		field.String("employee_number").Optional().Nillable().Comment("HR payroll number / staff ref"),
		field.String("first_name").Optional(),
		field.String("last_name").Optional(),
		field.String("email").Optional(),
		field.String("gender").Optional().Comment("male | female | other"),
		field.Time("date_of_birth").Optional().Nillable(),
		field.String("residential_status").Optional().Comment("Resident | Non-Resident"),

		// Statutory identifiers (KRA/SHIF/NSSF).
		field.String("national_id").Optional().Comment("National ID"),
		field.String("pin_no").Optional().Comment("KRA PIN"),
		field.String("shif_or_nhif_number").Optional().Nillable().Comment("SHIF (2024+) or NHIF number"),
		field.String("nssf_no").Optional(),

		// Governance flags — directors/shareholders are remunerated + exited under the
		// Companies Act 2015 (fees/dividends, removal by resolution), not the Employment Act.
		field.Bool("is_director").Default(false),
		field.Bool("is_shareholder").Default(false),

		field.Bool("terminated").Default(false),
		// TerminatedAt is when the employee was terminated (set on the change to terminated,
		// cleared on reinstatement); exits and turnover are counted from it.
		field.Time("terminated_at").Optional().Nillable(),
		// WorkShiftID is the employee's standard work shift: its weekly hours (total_hours_per_week,
		// else its working-day schedule) are the person's capacity that projects-api reads for
		// workload (owner, 17 November 2026). Unset means ERP holds no working hours for them.
		field.UUID("work_shift_id", uuid.UUID{}).Optional().Nillable().Comment("Standard work shift (FK -> work_shifts.id): weekly working hours"),
		field.Bool("deleted").Default(false).Comment("Soft delete (delete_status)"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (Employee) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "outlet_id"),
		index.Fields("tenant_id", "deleted"),
		index.Fields("tenant_id", "terminated_at"),
		// National ID unique within a tenant, never globally.
		index.Fields("tenant_id", "national_id").Unique(),
		index.Fields("user_id"),
	}
}
