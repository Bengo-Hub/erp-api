package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// RecoveryLine is the frozen snapshot of how much a payslip recovered against a specific
// recoverable (loan / advance / loss-damage / staff-purchase). It closes the missing repayment
// write-back: the payroll engine computes min(installment, outstanding) but never
// persisted it, so outstanding balances never decreased. A RecoveryLine is written at run time
// (frozen against the installment/outstanding as-of the run) and APPLIED at disburse time —
// incrementing the recoverable's amount_recovered exactly once, atomically with the batch.
type RecoveryLine struct {
	ent.Schema
}

func (RecoveryLine) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("payslip_id", uuid.UUID{}).Comment("FK -> payslip.id"),
		field.UUID("employee_id", uuid.UUID{}),

		field.Enum("recoverable_type").
			Values("loan", "advance", "loss_damage", "staff_purchase"),
		field.UUID("recoverable_id", uuid.UUID{}).Comment("FK -> the recoverable row of recoverable_type"),

		moneyField("amount"), // amount recovered this period (frozen at run time)

		field.String("batch_ref").Optional().Comment("Set to the disburse batch_ref when applied"),
		field.Bool("applied").Default(false).
			Comment("True once the amount has been written back to the recoverable (guards double-count)"),

		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (RecoveryLine) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("payslip_id"),
		index.Fields("tenant_id", "applied"),
		// One snapshot line per (payslip, recoverable) — a re-run replaces the unapplied line.
		index.Fields("payslip_id", "recoverable_type", "recoverable_id").Unique(),
	}
}
