package builders

import "fmt"

// Hex color strings (used by the XLSX generator and CSS).
const (
	HexSlate800 = "#1e293b"
	HexIndigo   = "#6366f1"
	HexSlate50  = "#f8fafc"
	HexSlate100 = "#f1f5f9"
	HexSlate200 = "#e2e8f0"
	HexSlate500 = "#64748b"
	HexWhite    = "#ffffff"
)

// HexToRGB parses a CSS hex color string (e.g. "#6366f1" or "6366f1") into 8-bit
// RGB components. ok is false when the input is not a valid 6-digit hex color.
func HexToRGB(hex string) (r, g, b int, ok bool) {
	if len(hex) > 0 && hex[0] == '#' {
		hex = hex[1:]
	}
	if len(hex) != 6 {
		return 0, 0, 0, false
	}
	var rr, gg, bb uint8
	if _, err := fmt.Sscanf(hex, "%02x%02x%02x", &rr, &gg, &bb); err != nil {
		return 0, 0, 0, false
	}
	return int(rr), int(gg), int(bb), true
}
