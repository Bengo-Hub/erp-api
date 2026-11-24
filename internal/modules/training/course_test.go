package training

import (
	"testing"
	"time"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

func TestCourseInputValidate(t *testing.T) {
	day := time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC)
	ok := CourseInput{Title: "First aid", StartDate: day, EndDate: day, Duration: "16", Cost: "12500.50", Status: "scheduled"}
	if err := ok.validate(); err != nil {
		t.Fatalf("valid course refused: %v", err)
	}
	bad := map[string]CourseInput{
		"no title":      {StartDate: day, EndDate: day},
		"end first":     {Title: "x", StartDate: day, EndDate: day.AddDate(0, 0, -1)},
		"text duration": {Title: "x", StartDate: day, EndDate: day, Duration: "two days"},
		"negative cost": {Title: "x", StartDate: day, EndDate: day, Cost: "-1"},
		"odd status":    {Title: "x", StartDate: day, EndDate: day, Status: "active"},
	}
	for name, in := range bad {
		if err := in.validate(); err == nil {
			t.Errorf("%s: must be refused", name)
		}
	}
}

func TestCourseMetadataRoundTrip(t *testing.T) {
	in := CourseInput{Provider: " Red Cross ", Duration: "16", Cost: "12500", Status: "ongoing"}
	md := in.metadata(map[string]any{"legacy": "kept", "cost": "1"})
	if md["legacy"] != "kept" || md["provider"] != "Red Cross" || md["cost"] != "12500" {
		t.Fatalf("metadata merge: %v", md)
	}
	v := ViewCourse(&ent.TrainingCourse{Title: "First aid", Metadata: md})
	if v.Provider != "Red Cross" || v.Duration != "16" || v.Cost != "12500" || v.Status != "ongoing" {
		t.Fatalf("view: %+v", v)
	}
	// A blank value removes the key; a course without a status reads as draft.
	md = CourseInput{}.metadata(md)
	if _, has := md["provider"]; has {
		t.Fatalf("blank provider must clear it: %v", md)
	}
	if ViewCourse(&ent.TrainingCourse{Metadata: md}).Status != "draft" {
		t.Fatal("missing status must read as draft")
	}
}
