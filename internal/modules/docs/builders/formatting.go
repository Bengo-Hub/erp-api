package builders

import (
	"fmt"
	"strings"
	"time"

	"github.com/shopspring/decimal"
)

// FormatMoney formats a monetary value with the given currency prefix and thousand separators.
func FormatMoney(currency string, v float64) string {
	return fmt.Sprintf("%s %s", currency, FormatFloat(v))
}

// FormatFloat formats a float64 with 2 decimal places and thousand separators.
func FormatFloat(v float64) string {
	s := fmt.Sprintf("%.2f", v)
	dec := s[len(s)-3:]
	intPart := s[:len(s)-3]
	out := ""
	for i, c := range intPart {
		pos := len(intPart) - i
		if i > 0 && pos%3 == 0 && intPart[0] != '-' {
			out += ","
		}
		out += string(c)
	}
	return out + dec
}

// FormatDate formats a time.Time as "02 Jan 2006".
func FormatDate(t time.Time) string {
	return t.Format("02 Jan 2006")
}

// AmountInWords converts a decimal amount to uppercase words for the given currency.
// e.g. AmountInWords("KES", 361800.00) → "THREE HUNDRED SIXTY ONE THOUSAND EIGHT HUNDRED SHILLINGS ONLY"
//
// The amount is first rounded to 2 decimal places so the words always agree with the
// 2-decimal total shown on the document (a raw 361799.9999 total displays as 361,800.00
// and must read "…EIGHT HUNDRED SHILLINGS ONLY", not "…NINETY NINE CENTS").
func AmountInWords(currency string, amount decimal.Decimal) string {
	amount = amount.Round(2)
	whole := amount.Floor().IntPart()
	cents := amount.Sub(decimal.NewFromInt(whole)).Mul(decimal.NewFromInt(100)).Round(0).IntPart()

	words := intToWords(whole)
	unitWord := currencyUnit(currency)

	result := strings.ToUpper(words) + " " + unitWord
	if cents > 0 {
		result += " AND " + strings.ToUpper(intToWords(cents)) + " CENTS"
	}
	return result + " ONLY"
}

func currencyUnit(currency string) string {
	switch strings.ToUpper(currency) {
	case "KES", "KSH":
		return "SHILLINGS"
	case "USD":
		return "DOLLARS"
	case "EUR":
		return "EUROS"
	case "GBP":
		return "POUNDS"
	case "UGX":
		return "UGANDA SHILLINGS"
	case "TZS":
		return "TANZANIA SHILLINGS"
	default:
		return strings.ToUpper(currency)
	}
}

var ones = []string{
	"", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
	"TEN", "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN",
	"SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN",
}

var tens = []string{
	"", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY",
}

func intToWords(n int64) string {
	if n == 0 {
		return "ZERO"
	}
	if n < 0 {
		return "MINUS " + intToWords(-n)
	}
	return strings.TrimSpace(convert(n))
}

func convert(n int64) string {
	switch {
	case n < 20:
		return ones[n]
	case n < 100:
		return tens[n/10] + " " + ones[n%10]
	case n < 1_000:
		return ones[n/100] + " HUNDRED " + convert(n%100)
	case n < 1_000_000:
		return convert(n/1_000) + " THOUSAND " + convert(n%1_000)
	case n < 1_000_000_000:
		return convert(n/1_000_000) + " MILLION " + convert(n%1_000_000)
	default:
		return convert(n/1_000_000_000) + " BILLION " + convert(n%1_000_000_000)
	}
}
