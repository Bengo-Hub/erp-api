package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ConsultantVoucher is a payment voucher for a consultant (an employee with employment_type=
// consultant, excluded from the PAYE run). Consultants are paid professional/consultancy fees
// subject to WITHHOLDING TAX (resident 5% / non-resident 20% on professional fees), NOT PAYE/
// statutory. net = gross − wht − deductions. On approval it emits erp.consultant_voucher.approved
// so treasury posts DR Consultant Fees (5600) / CR Accounts Payable (2050, net) / CR WHT Payable
// (2550), and the net is paid via the treasury payout S2S. The output document is a branded
// Payment Voucher (Doc No. via the payment_voucher sequence).
type ConsultantVoucher struct {
	ent.Schema
}

func (ConsultantVoucher) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id (the consultant)"),
		field.String("doc_number").Optional().Comment("VOC-… payment voucher number"),
		field.String("title").Optional().Comment("e.g. 'Consultant Payment for Dec 2024'"),
		field.Time("period").Optional().Nillable().Comment("First of the payment period/month"),

		moneyField("gross_amount"),     // total fees / earnings
		moneyField("deductions_amount"), // other deductions / loans
		rateField("wht_rate"),           // applied WHT rate (fraction, e.g. 0.05)
		moneyField("wht_amount"),
		moneyField("net_amount"), // gross − wht − deductions
		field.Bool("is_resident").Default(true).Comment("resident 5% vs non-resident 20% WHT"),
		field.String("currency").Default("KES"),

		field.UUID("project_id", uuid.UUID{}).Optional().Nillable().Comment("projects-service project id"),
		field.UUID("cost_center_id", uuid.UUID{}).Optional().Nillable().Comment("treasury cost-center id"),

		field.Enum("status").Values("draft", "pending", "approved", "paid").Default("draft"),
		field.String("email_status").Default("Draft"),
		field.Bool("published").Default(false),
		field.String("batch_ref").Optional(),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable(),
		field.UUID("approver_id", uuid.UUID{}).Optional().Nillable(),
		field.Time("approved_at").Optional().Nillable(),
		field.Bool("delete_status").Default(false),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ConsultantVoucher) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "status"),
		index.Fields("tenant_id", "employee_id"),
	}
}
