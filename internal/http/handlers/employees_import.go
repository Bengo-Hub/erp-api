package handlers

import (
	"encoding/csv"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
)

// importColumns is the accepted CSV header set (case-insensitive). employee_number,
// first_name, last_name are required; the rest are optional statutory identifiers.
var importColumns = []string{
	"employee_number", "first_name", "last_name", "email", "gender",
	"national_id", "pin_no", "shif_or_nhif_number", "nssf_no", "residential_status",
}

type importRowResult struct {
	Row            int    `json:"row"`
	EmployeeNumber string `json:"employee_number,omitempty"`
	Email          string `json:"email,omitempty"`
	Status         string `json:"status"` // created | error
	Error          string `json:"error,omitempty"`
}

type importSummary struct {
	Total   int               `json:"total"`
	Created int               `json:"created"`
	Failed  int               `json:"failed"`
	Results []importRowResult `json:"results"`
}

// Import bulk-creates employees from a CSV (POST /hrm/employees/import). Accepts a
// multipart "file" upload or a raw text/csv body. Each row is created independently:
// a bad/duplicate row is reported in its result and does NOT abort the batch.
func (h *EmployeesHandler) Import(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}

	body, err := readCSVBody(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	defer func() { _ = body.Close() }()

	reader := csv.NewReader(body)
	reader.TrimLeadingSpace = true
	reader.FieldsPerRecord = -1 // tolerate ragged rows; we map by header

	header, err := reader.Read()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "missing or unreadable CSV header row")
		return
	}
	colIdx := indexHeader(header)

	summary := importSummary{Results: []importRowResult{}}
	line := 1 // header consumed
	for {
		rec, rerr := reader.Read()
		if errors.Is(rerr, io.EOF) {
			break
		}
		line++
		if rerr != nil {
			summary.Failed++
			summary.Results = append(summary.Results, importRowResult{Row: line, Status: "error", Error: "malformed CSV row"})
			continue
		}
		if isBlankRecord(rec) {
			continue
		}
		summary.Total++
		get := func(col string) string {
			if i, ok := colIdx[col]; ok && i < len(rec) {
				return strings.TrimSpace(rec[i])
			}
			return ""
		}
		res := importRowResult{Row: line, EmployeeNumber: get("employee_number"), Email: get("email")}
		if get("first_name") == "" || get("last_name") == "" {
			res.Status = "error"
			res.Error = "first_name and last_name are required"
			summary.Failed++
			summary.Results = append(summary.Results, res)
			continue
		}
		in := employees.CreateInput{
			EmployeeNumber:    get("employee_number"),
			FirstName:         get("first_name"),
			LastName:          get("last_name"),
			Email:             get("email"),
			Gender:            get("gender"),
			NationalID:        get("national_id"),
			PinNo:             get("pin_no"),
			ShifOrNhifNumber:  get("shif_or_nhif_number"),
			NssfNo:            get("nssf_no"),
			ResidentialStatus: get("residential_status"),
		}
		// Restricted (single-outlet) users import into their own outlet.
		if scope.OutletID != uuid.Nil {
			oid := scope.OutletID
			in.OutletID = &oid
		}
		if _, cerr := h.svc.Create(r.Context(), scope.TenantID, in); cerr != nil {
			res.Status = "error"
			res.Error = cerr.Error()
			summary.Failed++
		} else {
			res.Status = "created"
			summary.Created++
		}
		summary.Results = append(summary.Results, res)
	}

	writeJSON(w, http.StatusOK, summary)
}

// readCSVBody returns the CSV stream from either a multipart "file" field or the raw body.
func readCSVBody(r *http.Request) (io.ReadCloser, error) {
	ct := r.Header.Get("Content-Type")
	if strings.HasPrefix(ct, "multipart/form-data") {
		if err := r.ParseMultipartForm(8 << 20); err != nil { // 8MB
			return nil, errors.New("invalid multipart form")
		}
		f, _, err := r.FormFile("file")
		if err != nil {
			return nil, errors.New("missing 'file' field in multipart upload")
		}
		return f, nil
	}
	if r.Body == nil {
		return nil, errors.New("empty request body")
	}
	return r.Body, nil
}

func indexHeader(header []string) map[string]int {
	idx := map[string]int{}
	for i, h := range header {
		key := strings.ToLower(strings.TrimSpace(h))
		key = strings.ReplaceAll(key, " ", "_")
		idx[key] = i
	}
	return idx
}

func isBlankRecord(rec []string) bool {
	for _, v := range rec {
		if strings.TrimSpace(v) != "" {
			return false
		}
	}
	return true
}
