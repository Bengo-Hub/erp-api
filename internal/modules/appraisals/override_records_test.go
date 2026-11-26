package appraisals

import (
	"encoding/json"
	"testing"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// TestOverridesReadMergeRecords: template, question and goal records exactly as
// ops/merge_inherited_settings.sql writes them (to_jsonb of bigint, double precision, text,
// boolean and the goal's jsonb metadata) are read and applied.
func TestOverridesReadMergeRecords(t *testing.T) {
	var tpls map[string]TemplateOverride
	if err := json.Unmarshal([]byte(`{"a": {"description": "", "is_active": false}}`), &tpls); err != nil {
		t.Fatal(err)
	}
	tpl := tpls["a"].apply(&ent.AppraisalTemplate{Name: "Standard", Description: "Yearly", IsActive: true})
	if tpl.Description != "" || tpl.IsActive || tpl.Name != "Standard" {
		t.Fatalf("template: %+v", tpl)
	}

	var qs map[string]QuestionOverride
	raw := `{"q": {"question_text": "Quality and accuracy", "is_required": false, "order": 3, "category": "", "weight": 12.5, "max_score": 10}}`
	if err := json.Unmarshal([]byte(raw), &qs); err != nil {
		t.Fatal(err)
	}
	q := qs["q"].apply(&ent.AppraisalQuestion{QuestionText: "Quality of Work", IsRequired: true, Order: 1, Category: "Competency", Weight: 20, MaxScore: 5})
	if q.QuestionText != "Quality and accuracy" || q.IsRequired || q.Order != 3 || q.Category != "" || q.Weight != 12.5 || q.MaxScore != 10 {
		t.Fatalf("question: %+v", q)
	}

	var goals map[string]GoalOverride
	if err := json.Unmarshal([]byte(`{"g": {"description": "By 30%", "metadata": {"category": "Quality", "weight": "40"}}}`), &goals); err != nil {
		t.Fatal(err)
	}
	g := goals["g"].apply(&ent.Goal{Title: "Reduce complaints", Description: "By 20%"})
	if g.Description != "By 30%" || g.Metadata["category"] != "Quality" || g.Metadata["weight"] != "40" {
		t.Fatalf("goal: %+v", g)
	}

	// The template list sends is_active even when it is false.
	raw2, err := json.Marshal(TemplateView{AppraisalTemplate: tpl, IsActive: tpl.IsActive})
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err := json.Unmarshal(raw2, &out); err != nil || out["is_active"] != false {
		t.Fatalf("template view: %s", raw2)
	}
}
