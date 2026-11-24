// Package treasury is a service-to-service client for treasury-api. erp-api uses it only
// to request payroll net-pay disbursement (POST /s2s/{tenant}/payouts/disburse). Treasury
// remains the single source of truth for money movement + GL; erp-api never posts ledgers.
//
// The S2S transport is the shared github.com/Bengo-Hub/shared-service-client (circuit
// breaker + retry + tracing + tenant/request-id header propagation). erp-api layers the
// shared INTERNAL_SERVICE_KEY (X-API-Key) and a per-batch Idempotency-Key on top.
package treasury

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	serviceclient "github.com/Bengo-Hub/shared-service-client"
	"github.com/google/uuid"
	"go.uber.org/zap"
)

// ErrApprovalPending is returned by Disburse when treasury blocks the payroll batch pending finance
// approval (HTTP 409 approval_required). It is NOT a transport failure: the GL event is already
// published; the operator re-triggers disburse once the batch is approved (with OTP) in treasury.
var ErrApprovalPending = errors.New("treasury: payroll disbursement pending finance approval")

// Payout is one net-pay disbursement line. Amounts are decimal STRINGS, never
// float, across the disburse boundary.
type Payout struct {
	RecipientID   string `json:"recipient_id"`
	Amount        string `json:"amount"`
	Currency      string `json:"currency"`
	PaymentMethod string `json:"payment_method"`
	// Phone is the mobile-money MSISDN for mobile payout channels (mpesa_b2c/airtel/paystack_mobile).
	Phone       string `json:"phone,omitempty"`
	ReferenceID string `json:"reference_id"`
	Description string `json:"description"`
}

// Client calls treasury-api over S2S (X-API-Key: INTERNAL_SERVICE_KEY) using the shared
// service client for resilience (retry/circuit-breaker) and header propagation.
type Client struct {
	apiKey  string
	baseURL string
	enabled bool
	sc      *serviceclient.Client
	httpc   *http.Client
	log     *zap.Logger
}

// NewClient builds the treasury S2S client. apiKey is the shared INTERNAL_SERVICE_KEY.
// When baseURL or apiKey is empty the client is disabled (Disburse becomes a no-op).
func NewClient(baseURL, apiKey string, log *zap.Logger) *Client {
	log = log.Named("treasury.client")
	baseURL = strings.TrimRight(baseURL, "/")
	enabled := baseURL != "" && apiKey != ""
	var sc *serviceclient.Client
	if enabled {
		cfg := serviceclient.DefaultConfig(baseURL, "treasury-api", log)
		cfg.Timeout = 12 * time.Second
		sc = serviceclient.New(cfg)
	}
	return &Client{
		apiKey:  apiKey,
		baseURL: baseURL,
		enabled: enabled,
		sc:      sc,
		httpc:   &http.Client{Timeout: 10 * time.Second},
		log:     log,
	}
}

// ListBanks proxies the treasury S2S Paystack bank list for a country (raw JSON passthrough).
func (c *Client) ListBanks(ctx context.Context, tenantID uuid.UUID, country string) (json.RawMessage, error) {
	if !c.enabled {
		return nil, fmt.Errorf("treasury client not configured")
	}
	if country == "" {
		country = "kenya"
	}
	return c.getRaw(ctx, fmt.Sprintf("%s/api/v1/s2s/%s/gateways/banks/%s", c.baseURL, tenantID.String(), country))
}

// ResolveAccount proxies the treasury S2S Paystack account name-enquiry (raw JSON passthrough).
func (c *Client) ResolveAccount(ctx context.Context, tenantID uuid.UUID, accountNumber, bankCode string) (json.RawMessage, error) {
	if !c.enabled {
		return nil, fmt.Errorf("treasury client not configured")
	}
	return c.getRaw(ctx, fmt.Sprintf("%s/api/v1/s2s/%s/gateways/resolve-account?account_number=%s&bank_code=%s",
		c.baseURL, tenantID.String(), url.QueryEscape(accountNumber), url.QueryEscape(bankCode)))
}

func (c *Client) getRaw(ctx context.Context, fullURL string) (json.RawMessage, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, fullURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-API-Key", c.apiKey)
	resp, err := c.httpc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("treasury: %s status %d", fullURL, resp.StatusCode)
	}
	return json.RawMessage(body), nil
}

// ClaimCheck is what treasury needs to check a staff claim against the tenant's budgets.
type ClaimCheck struct {
	ClaimID      string  `json:"claim_id"`
	ClaimType    string  `json:"claim_type"`
	Amount       string  `json:"amount"`
	Currency     string  `json:"currency"`
	Taxable      bool    `json:"taxable"`
	ProjectID    *string `json:"project_id,omitempty"`
	CostCenterID *string `json:"cost_center_id,omitempty"`
	Date         string  `json:"date,omitempty"`
}

// BudgetResult is treasury's answer: action ok, warn or stop, with the budget lines concerned.
type BudgetResult struct {
	Action string          `json:"action"`
	Lines  json.RawMessage `json:"lines"`
}

// CheckClaimBudget asks treasury whether approving the claim stays within budget. It fails open:
// an unconfigured client or an unreachable treasury answers ok, so budgets never block payroll
// work because another service is down (the stop is a control, not a dependency).
func (c *Client) CheckClaimBudget(ctx context.Context, tenantID uuid.UUID, in ClaimCheck) BudgetResult {
	ok := BudgetResult{Action: "ok"}
	if !c.enabled {
		return ok
	}
	path := fmt.Sprintf("/api/v1/s2s/%s/budgets/claim-check", tenantID.String())
	resp, err := c.sc.Post(ctx, path, in, map[string]string{"X-API-Key": c.apiKey, "X-Tenant-ID": tenantID.String()})
	if err != nil || !resp.IsSuccess() {
		c.log.Warn("claim budget check unavailable; allowing", zap.Error(err))
		return ok
	}
	var out BudgetResult
	if err := json.Unmarshal(resp.Body, &out); err != nil || out.Action == "" {
		return ok
	}
	return out
}

// Enabled reports whether the client is configured for S2S calls.
func (c *Client) Enabled() bool { return c.enabled }

// ErrNotConfigured is returned by DisburseBatch when the client has no treasury URL or key, so
// nothing was sent and nothing may be recorded as paid.
var ErrNotConfigured = errors.New("treasury: payouts are not configured")

// ErrPartialDisburse is returned by Disburse when treasury accepted the batch but did not
// dispatch every item. A retry with the same references pays only the failed items, because
// treasury refuses a second payout for a reference that is not failed.
var ErrPartialDisburse = errors.New("treasury: some payouts were not dispatched")

// BatchResult is treasury's answer to a batch disbursement: one entry per item, keyed by the
// item's reference. Status "dispatched" means treasury has sent (or already holds) that payout.
type BatchResult struct {
	Count      int           `json:"count"`
	Dispatched int           `json:"dispatched"`
	Results    []ItemOutcome `json:"results"`
}

// ItemOutcome is the outcome of one payout in a batch.
type ItemOutcome struct {
	Reference string `json:"reference"`
	Status    string `json:"status"`
	Error     string `json:"error,omitempty"`
}

// DispatchedRefs is the set of references treasury dispatched.
func (b BatchResult) DispatchedRefs() map[string]bool {
	out := make(map[string]bool, len(b.Results))
	for _, r := range b.Results {
		if r.Status == "dispatched" {
			out[r.Reference] = true
		}
	}
	return out
}

// DisburseBatch POSTs the payouts to treasury and returns the per-item outcome. idempotencyKey
// is sent as Idempotency-Key: treasury binds its finance approval to that key and the exact
// items, and refuses a second payout for any reference it already holds, so a re-sent batch
// never pays an item twice. A blocked batch returns ErrApprovalPending.
func (c *Client) DisburseBatch(ctx context.Context, tenantID uuid.UUID, payouts []Payout, idempotencyKey string) (BatchResult, error) {
	if !c.enabled {
		return BatchResult{}, ErrNotConfigured
	}
	if len(payouts) == 0 {
		return BatchResult{}, nil
	}
	headers := map[string]string{"X-API-Key": c.apiKey}
	if idempotencyKey != "" {
		headers["Idempotency-Key"] = idempotencyKey
	}
	path := fmt.Sprintf("/api/v1/s2s/%s/payouts/disburse", tenantID.String())
	resp, err := c.sc.Post(ctx, path, map[string]any{"payouts": payouts}, headers)
	if err != nil {
		return BatchResult{}, fmt.Errorf("treasury: disburse: %w", err)
	}
	if resp.StatusCode == http.StatusConflict {
		return BatchResult{}, ErrApprovalPending
	}
	if !resp.IsSuccess() {
		return BatchResult{}, fmt.Errorf("treasury: disburse: status %d", resp.StatusCode)
	}
	var out BatchResult
	if err := json.Unmarshal(resp.Body, &out); err != nil {
		return BatchResult{}, fmt.Errorf("treasury: disburse: read result: %w", err)
	}
	return out, nil
}

// Disburse is DisburseBatch for callers that need all-or-nothing: it returns ErrPartialDisburse
// unless every item was dispatched, and ErrNotConfigured when treasury is not set up.
func (c *Client) Disburse(ctx context.Context, tenantID uuid.UUID, payouts []Payout, idempotencyKey string) error {
	res, err := c.DisburseBatch(ctx, tenantID, payouts, idempotencyKey)
	if err != nil {
		return err
	}
	if len(payouts) > 0 && res.Dispatched < len(payouts) {
		return fmt.Errorf("%w: %d of %d", ErrPartialDisburse, res.Dispatched, len(payouts))
	}
	return nil
}
