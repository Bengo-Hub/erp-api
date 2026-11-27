package orgsettings

import (
	"errors"
	"fmt"

	"github.com/shopspring/decimal"
)

// Values kept in a reference row's metadata, by the key the API and the forms use: a job title's
// code, a department's description, and a job group's grade and salary range.
const (
	ExtraCode        = "code"
	ExtraDescription = "description"
	ExtraGrade       = "grade"
	ExtraMinSalary   = "min_salary"
	ExtraMaxSalary   = "max_salary"
)

// The metadata keys each kind keeps (description is a column on job titles and job groups).
var (
	departmentExtras = []string{ExtraDescription}
	jobTitleExtras   = []string{ExtraCode}
	jobGroupExtras   = []string{ExtraGrade, ExtraMinSalary, ExtraMaxSalary}
)

// ErrSalaryRange refuses a job group salary range that is not two amounts, lowest first.
var ErrSalaryRange = errors.New("the salary range needs amounts of 0 or more, the minimum not above the maximum")

// ExtraOf reads one metadata value as text ("" when unset).
func ExtraOf(meta map[string]any, key string) string {
	if v, ok := meta[key].(string); ok {
		return v
	}
	return ""
}

// mergeExtra applies the sent values of the given keys to a copy of meta: "" removes a key, a
// key not sent keeps its value. It returns nil when nothing is left.
func mergeExtra(meta map[string]any, sent map[string]string, keys []string) map[string]any {
	out := map[string]any{}
	for k, v := range meta {
		out[k] = v
	}
	for _, k := range keys {
		v, ok := sent[k]
		if !ok {
			continue
		}
		if v == "" {
			delete(out, k)
		} else {
			out[k] = v
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

// checkSalaryRange validates the job group salary range a merged metadata holds.
func checkSalaryRange(meta map[string]any) error {
	var lo, hi *decimal.Decimal
	for key, dst := range map[string]**decimal.Decimal{ExtraMinSalary: &lo, ExtraMaxSalary: &hi} {
		s := ExtraOf(meta, key)
		if s == "" {
			continue
		}
		d, err := decimal.NewFromString(s)
		if err != nil || d.IsNegative() {
			return fmt.Errorf("%w (%s %q)", ErrSalaryRange, key, s)
		}
		*dst = &d
	}
	if lo != nil && hi != nil && lo.GreaterThan(*hi) {
		return ErrSalaryRange
	}
	return nil
}
