package handlers

import (
	"encoding/json"
	"testing"

	"github.com/google/uuid"
)

func TestEmployeeHRFieldsFormAndAPINames(t *testing.T) {
	dept, title := uuid.New(), uuid.New()
	var b updateEmployeeBody
	// The employee form sends department / job_title and kra_pin.
	raw := `{"department":"` + dept.String() + `","job_title":"` + title.String() +
		`","employment_type":"contract","date_joined":"2026-03-01T00:00:00Z","kra_pin":"A123"}`
	if err := json.Unmarshal([]byte(raw), &b); err != nil {
		t.Fatal(err)
	}
	in, err := b.hrInput()
	if err != nil {
		t.Fatal(err)
	}
	if in.DepartmentID == nil || *in.DepartmentID != dept || in.JobTitleID == nil || *in.JobTitleID != title {
		t.Fatalf("ids not mapped: %+v", in)
	}
	if in.DateJoined == nil || in.DateJoined.Format("2006-01-02") != "2026-03-01" {
		t.Fatalf("date_joined not parsed: %+v", in.DateJoined)
	}
	if b.KraPin == nil || *b.KraPin != "A123" {
		t.Fatal("kra_pin alias not decoded")
	}

	// The *_id names win, and "" clears.
	var c updateEmployeeBody
	_ = json.Unmarshal([]byte(`{"department":"`+dept.String()+`","department_id":"","reports_to_id":""}`), &c)
	in, err = c.hrInput()
	if err != nil || in.DepartmentID == nil || *in.DepartmentID != uuid.Nil || in.ReportsToID == nil || *in.ReportsToID != uuid.Nil {
		t.Fatalf("clear not honoured: %+v %v", in, err)
	}

	// date_joined: "" clears (zero time), a bad date is refused, absent is no change.
	var j updateEmployeeBody
	_ = json.Unmarshal([]byte(`{"date_joined":""}`), &j)
	if in, err := j.hrInput(); err != nil || in.DateJoined == nil || !in.DateJoined.IsZero() || in.Empty() {
		t.Fatalf("blank date_joined must clear: %+v %v", in, err)
	}
	var k updateEmployeeBody
	_ = json.Unmarshal([]byte(`{"date_joined":"01/02/2026"}`), &k)
	if _, err := k.hrInput(); err == nil {
		t.Fatal("bad date_joined must be rejected")
	}

	var d updateEmployeeBody
	_ = json.Unmarshal([]byte(`{"department":"not-a-uuid"}`), &d)
	if _, err := d.hrInput(); err == nil {
		t.Fatal("bad uuid must be rejected")
	}
	if in, _ := (updateEmployeeBody{}).hrInput(); !in.Empty() {
		t.Fatal("no fields must mean no change")
	}
}
