package attendance

import (
	"testing"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

func TestDeviceAllowsIP(t *testing.T) {
	open := &ent.AttendanceDevice{}
	if !DeviceAllowsIP(open, "203.0.113.9") {
		t.Fatal("a device without an allow list accepts any address")
	}
	dev := &ent.AttendanceDevice{Metadata: map[string]any{
		"allowed_cidrs": []any{"41.90.0.0/16", "197.232.10.5", " "},
	}}
	cases := map[string]bool{
		"41.90.12.7":          true,  // inside the CIDR
		"197.232.10.5":        true,  // exact address
		"::ffff:197.232.10.5": true,  // IPv4-mapped form of the same address
		"197.232.10.6":        false, // neighbour of the exact address
		"102.0.0.1":           false,
		"not-an-ip":           false,
		"":                    false,
	}
	for ip, want := range cases {
		if got := DeviceAllowsIP(dev, ip); got != want {
			t.Errorf("DeviceAllowsIP(%q) = %v, want %v", ip, got, want)
		}
	}
}
