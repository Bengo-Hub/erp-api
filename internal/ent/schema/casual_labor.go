package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// CasualLaborRecord is a documented record of casual / subcontracted labour engaged for a task —
// e.g. a project manager or consultant who hires casual workers (or their own hired skills) to do
// project tasks and is reimbursed by the company. It gives that informal arrangement a paper trail
// + approval chain + GL posting, so the cost is captured in the books and attributed to a project.
type CasualLaborRecord struct {
	ent.Schema
}

func (CasualLaborRecord) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		// engaged_by_employee_id is the employee/consultant/PM who engaged + (usually) paid the
		// casual worker and is reimbursed via an expense claim or imprest retirement.
		field.UUID("engaged_by_employee_id", uuid.UUID{}).Optional().Nillable().
			Comment("Employee/consultant/PM who engaged the casual worker"),
		field.UUID("project_id", uuid.UUID{}).Optional().Nillable().Comment("projects-service project id"),
		field.UUID("cost_center_id", uuid.UUID{}).Optional().Nillable().Comment("treasury cost-center id"),
		field.String("worker_name").NotEmpty().Comment("Casual worker / hired skill name"),
		field.String("worker_id_number").Optional().Comment("National ID / reference for the worker"),
		field.String("worker_phone").Optional(),
		field.Text("task_description").Optional().Comment("What work was done"),
		moneyField("amount"),
		field.Time("work_date").Optional().Nillable(),
		// payment_method: how the worker was paid (cash/mpesa/etc.) by the engager.
		field.String("payment_method").Optional(),
		// status: pending -> approved -> paid (paid = reimbursed/settled). rejected is terminal.
		field.Enum("status").Values("pending", "approved", "rejected", "paid").Default("pending"),
		field.UUID("approver_id", uuid.UUID{}).Optional().Nillable(),
		field.Time("approved_at").Optional().Nillable(),
		// imprest_advance_id optionally links to a salary-advance/imprest used as the float the
		// engager drew to pay casual workers — so this record retires (accounts for) that advance.
		field.UUID("imprest_advance_id", uuid.UUID{}).Optional().Nillable().
			Comment("Advance/imprest this record retires, when paid from a float"),
		field.String("attachment_url").Optional().Nillable(),
		field.Bool("delete_status").Default(false),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (CasualLaborRecord) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "project_id"),
		index.Fields("tenant_id", "engaged_by_employee_id"),
	}
}
