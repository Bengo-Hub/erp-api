package reports

import (
	"testing"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

func TestSlipEmployeeIDsAndChunks(t *testing.T) {
	a, b := uuid.New(), uuid.New()
	cur := []*ent.Payslip{{EmployeeID: a}, {EmployeeID: a}, {EmployeeID: b}}
	prev := []*ent.Payslip{{EmployeeID: b}}
	if ids := slipEmployeeIDs(cur, prev); len(ids) != 2 || ids[0] != a || ids[1] != b {
		t.Fatalf("distinct employees in order = %v", ids)
	}
	if got := slipEmployeeIDs(); len(got) != 0 {
		t.Fatalf("no slips = %v", got)
	}
	ids := make([]uuid.UUID, 2500)
	chunks := idChunks(ids)
	if len(chunks) != 3 || len(chunks[0]) != 1000 || len(chunks[2]) != 500 {
		t.Fatalf("chunks = %d", len(chunks))
	}
	if len(idChunks(nil)) != 0 {
		t.Fatal("no ids, no chunks")
	}
}
