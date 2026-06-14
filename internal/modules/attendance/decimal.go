package attendance

import "github.com/shopspring/decimal"

// parseDecimal parses a required decimal string.
func parseDecimal(s string) (decimal.Decimal, error) {
	return decimal.NewFromString(s)
}

// parseDecimalDefault parses a decimal string, returning zero for an empty value.
func parseDecimalDefault(s string) (decimal.Decimal, error) {
	if s == "" {
		return decimal.Zero, nil
	}
	return decimal.NewFromString(s)
}
