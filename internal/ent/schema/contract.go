package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Contract is an employment contract (legacy hrm.employees.Contract). Duration is
// recomputed on write (data-migration §4 stale-derived fix).
type Contract struct {
	ent.Schema
}

func (Contract) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),

		field.String("contract_type").Optional(),
		field.Time("start_date").Optional().Nillable(),
		field.Time("end_date").Optional().Nillable(),
		field.Int("duration_months").Optional().Comment("Recomputed from start/end on write"),
		moneyField("salary"),
		field.String("status").Default("active").Comment("active | expired | terminated"),
		field.Text("terms_html").Optional().Comment("Editable rich-text (HTML) body of the employment terms/contract"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (Contract) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
	}
}
