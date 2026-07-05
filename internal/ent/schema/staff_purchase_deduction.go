package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// StaffPurchaseDeduction is a POS-origin staff purchase (goods taken on credit or layaway at the
// point of sale, funded from the employee's salary) recovered via payroll deductions. It is a
// dedicated recoverable — kept distinct from HR salary Advances/Loans — carrying the POS source
// references + an idempotency key so the pos-api ↔ erp-api sync never double-creates it. The
// payroll engine recovers it in the after-PAYE phase like other recoverables (min installment/
// outstanding); erp publishes erp.staff_purchase.recovered so POS pays down the linked balance.
type StaffPurchaseDeduction struct {
	ent.Schema
}

func (StaffPurchaseDeduction) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id (resolved from the auth user id)"),

		field.Enum("origin").Values("layaway", "credit_sale").
			Comment("What the staff purchase originated from at POS"),
		field.String("pos_reference").Optional().
			Comment("POS layaway_plan.id or pos_order.id (display/trace)"),
		field.String("source_key").NotEmpty().
			Comment("POS-supplied idempotency key, e.g. pos:layaway:<id>; unique per tenant"),

		moneyField("principal"),          // amount owed (pushed from POS)
		moneyField("amount_recovered"),   // running total recovered via payroll (starts 0)
		moneyField("installment_amount"), // per-period deduction
		field.Int("installments_total").Optional().
			Comment("Informational cap on the number of payroll periods"),

		field.Enum("status").Values("active", "settled", "cancelled").Default("active"),
		field.Bool("is_active").Default(true).
			Comment("Engine filter parity with loans/advances; false once settled/cancelled"),

		field.String("last_settled_batch").Optional().
			Comment("Last payroll batch_ref that recovered against this (audit)"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (StaffPurchaseDeduction) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id", "is_active"),
		index.Fields("tenant_id", "source_key").Unique(),
	}
}
