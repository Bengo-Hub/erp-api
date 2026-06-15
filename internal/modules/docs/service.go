package docs

import "fmt"

// Format identifies the output format for document generation.
type Format string

const (
	FormatPDF  Format = "pdf"
	FormatCSV  Format = "csv"
	FormatXLSX Format = "xlsx"
)

const (
	MimePDF  = "application/pdf"
	MimeCSV  = "text/csv"
	MimeXLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

// DocumentService is the facade for generating ERP documents in all formats.
type DocumentService struct{}

// Generate produces document bytes in the requested format, returning (bytes, mimeType, error).
func (s *DocumentService) Generate(doc *Document, format Format) ([]byte, string, error) {
	switch format {
	case FormatPDF:
		b, err := GeneratePDF(doc)
		return b, MimePDF, err
	case FormatCSV:
		b, err := GenerateCSV(doc)
		return b, MimeCSV, err
	case FormatXLSX:
		b, err := GenerateXLSX(doc)
		return b, MimeXLSX, err
	default:
		return nil, "", fmt.Errorf("unsupported document format: %q", format)
	}
}

// FormatFromString parses a query param string into a Format.
func FormatFromString(s string) (Format, error) {
	switch s {
	case "pdf":
		return FormatPDF, nil
	case "csv":
		return FormatCSV, nil
	case "xlsx", "excel":
		return FormatXLSX, nil
	default:
		return "", fmt.Errorf("unsupported format %q: must be pdf, csv, or xlsx", s)
	}
}
