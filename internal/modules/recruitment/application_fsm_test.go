package recruitment

import (
	"testing"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/application"
)

func TestSplitFullName(t *testing.T) {
	cases := map[string][2]string{
		"Jane Wanjiru Mwangi": {"Jane", "Wanjiru Mwangi"},
		"  Peter  ":           {"Peter", ""},
		"":                    {"", ""},
	}
	for in, want := range cases {
		f, l := splitFullName(in)
		if f != want[0] || l != want[1] {
			t.Errorf("%q: got %q %q, want %q %q", in, f, l, want[0], want[1])
		}
	}
}

func TestCandidateSourceAndStatus(t *testing.T) {
	if err := (CandidateInput{FullName: "Jane", Status: "hired"}).validate(); err != nil {
		t.Fatal(err)
	}
	if err := (CandidateInput{FullName: "Jane", Status: "offer"}).validate(); err == nil {
		t.Fatal("unknown status must be refused")
	}
	if err := (CandidateInput{FullName: "  "}).validate(); err == nil {
		t.Fatal("blank name must be refused")
	}
	md := CandidateInput{Source: " LinkedIn "}.metadata(map[string]any{"other": 1})
	v := ViewCandidate(&ent.Candidate{Metadata: md})
	if v.Source != "LinkedIn" || v.Status != "new" || md["other"] != 1 {
		t.Fatalf("view %+v metadata %v", v, md)
	}
	md = CandidateInput{Status: "on_hold"}.metadata(md)
	if _, has := md["source"]; has || ViewCandidate(&ent.Candidate{Metadata: md}).Status != "on_hold" {
		t.Fatalf("blank source must clear it and status must update: %v", md)
	}
	if ViewCandidate(&ent.Candidate{}).Status != "new" {
		t.Fatal("a candidate without metadata reads as new")
	}
}

// TestPipelineStages pins the stage order the UI offers as next steps.
func TestPipelineStages(t *testing.T) {
	ok := [][2]application.Status{
		{application.StatusApplied, application.StatusScreening},
		{application.StatusScreening, application.StatusInterview},
		{application.StatusInterview, application.StatusOffered},
		{application.StatusOffered, application.StatusHired},
		{application.StatusApplied, application.StatusRejected},
		{application.StatusOffered, application.StatusRejected},
	}
	for _, c := range ok {
		if !canTransition(c[0], c[1]) {
			t.Errorf("%s -> %s must be allowed", c[0], c[1])
		}
	}
	bad := [][2]application.Status{
		{application.StatusApplied, application.StatusOffered},
		{application.StatusInterview, application.Status("offer")},
		{application.StatusHired, application.StatusRejected},
		{application.StatusRejected, application.StatusScreening},
	}
	for _, c := range bad {
		if canTransition(c[0], c[1]) {
			t.Errorf("%s -> %s must be refused", c[0], c[1])
		}
	}
}

func TestOfferStartDate(t *testing.T) {
	str := func(s string) *string { return &s }
	cases := map[*string]string{
		nil: "",
		str("KES 80,000. Start date: 2026-12-01"):     "2026-12-01",
		str("starting 2027-01-04, 3 month probation"): "2027-01-04",
		str("Start=2026-11-30"):                       "2026-11-30",
		str("Offer sent 2026-10-01, salary 50k"):      "",
		str("Start date: 2026-13-45"):                 "",
	}
	for in, want := range cases {
		got := offerStartDate(in)
		if (got == nil) != (want == "") || (got != nil && got.Format("2006-01-02") != want) {
			t.Errorf("%v: got %v, want %q", in, got, want)
		}
	}
}
