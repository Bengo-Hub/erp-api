package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/dialect"
	"entgo.io/ent/dialect/entsql"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ExpenseClaim is an employee expense claim (legacy hrm.payroll.ExpenseClaims).
type ExpenseClaim struct {
	ent.Schema
}

func (ExpenseClaim) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("approver_id", uuid.UUID{}).Optional().Nillable(),

		field.Bool("approved").Default(false),
		// project_id + cost_center_id tag the claim to an analytic dimension so the cost posts
		// against a project / cost-center in treasury (projects-expense integration is delivered
		// via project-tagged ERP claims — projects-api owns no expense module).
		field.UUID("project_id", uuid.UUID{}).Optional().Nillable().Comment("projects-service project id"),
		field.UUID("cost_center_id", uuid.UUID{}).Optional().Nillable().Comment("treasury cost-center id"),
		// claim_type drives tax treatment: per_diem/mileage have KRA caps (excess is taxable),
		// reimbursement is a bona-fide non-taxable business expense, other defaults taxable=false.
		field.String("claim_type").Default("reimbursement").
			Comment("per_diem | mileage | reimbursement | other"),
		// taxable marks the (portion treated as) taxable income — the taxable amount flows to the
		// payslip for PAYE; the non-taxable remainder is reimbursed via treasury AP (not payroll).
		field.Bool("taxable").Default(false),
		field.String("category").Optional().Comment("Other | Mileage"),
		field.Time("application_date").Optional().Nillable(),
		field.Time("payment_date").Optional().Nillable(),
		field.String("attachment_url").Optional().Nillable(),
		moneyField("amount"),
		field.Bool("is_active").Default(true),
		field.Bool("is_paid").Default(false),
		field.Bool("schedule_to_payroll").Default(false),
		field.Bool("delete_status").Default(false),
		// metadata carries claim provenance for claims raised by other services, e.g.
		// {"source":"logistics","source_key":"logistics:task:<id>:per_diem","days":2,...}.
		field.JSON("metadata", map[string]any{}).Optional(),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ExpenseClaim) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
		// GIN so the source_key containment lookup for external claims stays an index scan.
		index.Fields("metadata").
			Annotations(entsql.IndexTypes(map[string]string{dialect.Postgres: "GIN"})),
	}
}
