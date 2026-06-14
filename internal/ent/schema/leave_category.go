package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// LeaveCategory is a tenant-scoped leave type with accrual/carryover config (legacy
// hrm.leave.LeaveCategory). Drives the leave-accrual cron (replaces accrue_leave.py).
type LeaveCategory struct {
	ent.Schema
}

func (LeaveCategory) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant — REQUIRED for isolation"),
		field.String("name"),
		field.String("description").Optional(),
		field.Bool("is_active").Default(true),
		// default_annual_days: default yearly entitlement for this category.
		daysField("default_annual_days"),
		field.Bool("allow_carryover").Default(false),
		// max_carryover_days: cap on days carried over (0 = unlimited when allow_carryover).
		daysField("max_carryover_days"),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (LeaveCategory) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "is_active"),
		index.Fields("tenant_id", "name").Unique(),
	}
}
