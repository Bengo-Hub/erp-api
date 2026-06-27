package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// CasualPayment is the unified casual-payments register. ONE row is one payment to a casual,
// covering BOTH wingubox scenarios via settlement_mode:
//
//   - direct_payout    — a registered casual EMPLOYEE (employment_type=casual) paid directly by
//     the company per unit: daily/hourly wages, overtime, payment-in-lieu (quantity × rate).
//     GL: DR wages / CR cash·bank. Aggregates into the casual muster/payout.
//   - reimburse_engager — an informal/sub-contracted worker (worker_name, no employee record)
//     paid by a PM/consultant who is then reimbursed by the company (often retiring an imprest
//     advance). GL: DR casual-labour / CR engager-payable.
//
// These are NOT run through the PAYE engine (casuals are daily-rated; statutory only applies above
// the monthly threshold, handled separately).
type CasualPayment struct {
	ent.Schema
}

func (CasualPayment) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.Enum("settlement_mode").
			Values("direct_payout", "reimburse_engager").Default("direct_payout"),

		// direct_payout: the registered casual employee being paid.
		field.UUID("employee_id", uuid.UUID{}).Optional().Nillable().Comment("FK -> employee.id (casual employee)"),
		// reimburse_engager: informal worker + who engaged/paid them + the float being retired.
		field.String("worker_name").Optional().Comment("Informal worker / hired-skill name (reimburse mode)"),
		field.String("worker_id_number").Optional(),
		field.String("worker_phone").Optional(),
		field.UUID("engaged_by_employee_id", uuid.UUID{}).Optional().Nillable().
			Comment("Employee/PM who engaged + paid the informal worker (reimburse mode)"),
		field.UUID("imprest_advance_id", uuid.UUID{}).Optional().Nillable().
			Comment("Advance/imprest this payment retires, when paid from a float"),

		// wage_type: the addition kind (wingubox Add Casual Payments dropdown). lump_sum = a flat
		// payment (reimbursement or one-off), stored as quantity 1 × rate amount.
		field.Enum("wage_type").
			Values("daily_wages", "hourly_wages", "overtime_1_5x", "overtime_2x", "payment_in_lieu", "lump_sum").
			Default("daily_wages"),
		daysField("quantity"), // days / hours / units (1 for lump_sum)
		moneyField("rate"),
		moneyField("amount"), // quantity × rate (computed on write)

		field.Text("task_description").Optional(),
		field.Time("work_date").Optional().Nillable(),
		field.Time("payment_date").Optional().Nillable(),
		field.Time("payroll_month").Optional().Nillable().Comment("First of the payroll month (direct_payout casuals)"),
		field.UUID("project_id", uuid.UUID{}).Optional().Nillable().Comment("projects-service project id"),
		field.UUID("cost_center_id", uuid.UUID{}).Optional().Nillable().Comment("treasury cost-center id"),
		// payment_option: bank_transfer | equity_bank | mobile_money | cash | cheque (settlement rail).
		field.String("payment_option").Optional(),

		field.Enum("status").Values("pending", "approved", "paid").Default("pending"),
		field.UUID("approver_id", uuid.UUID{}).Optional().Nillable(),
		field.Time("approved_at").Optional().Nillable(),
		field.String("attachment_url").Optional().Nillable(),
		field.Bool("delete_status").Default(false),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (CasualPayment) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "settlement_mode"),
		index.Fields("tenant_id", "payroll_month"),
		index.Fields("tenant_id", "employee_id"),
		index.Fields("tenant_id", "project_id"),
	}
}
