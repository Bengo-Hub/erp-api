package middleware

import (
	"reflect"
	"testing"
)

func TestMapGlobalRolesToERP(t *testing.T) {
	cases := []struct {
		name string
		in   []string
		want []string
	}{
		{"superuser maps to erp_admin", []string{"superuser"}, []string{"erp_admin"}},
		{"admin maps to erp_admin", []string{"admin"}, []string{"erp_admin"}},
		{"legacy superusers group maps to erp_admin", []string{"superusers"}, []string{"erp_admin"}},
		{"case-insensitive", []string{"Admin", "SUPERUSER"}, []string{"erp_admin"}},
		{"erp role passes through", []string{"hr_manager"}, []string{"hr_manager"}},
		{"known erp role passes through", []string{"finance_manager"}, []string{"finance_manager"}},
		{"mixed dedupes admin", []string{"superuser", "admin", "payroll_manager"}, []string{"erp_admin", "payroll_manager"}},
		{"blanks skipped", []string{"", "  ", "hr_viewer"}, []string{"hr_viewer"}},
		{"empty input", nil, []string{}},
		{"non-hrm role defaults to staff", []string{"cashier"}, []string{"staff"}},
		{"multiple non-hrm roles dedupe to one staff", []string{"rider", "driver", "waiter"}, []string{"staff"}},
		{"non-hrm role case-insensitive", []string{"Cashier"}, []string{"staff"}},
		{"mixed hrm + non-hrm keeps both", []string{"hr_manager", "cashier"}, []string{"hr_manager", "staff"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := MapGlobalRolesToERP(tc.in)
			if !reflect.DeepEqual(got, tc.want) {
				t.Errorf("MapGlobalRolesToERP(%v) = %v, want %v", tc.in, got, tc.want)
			}
		})
	}
}
