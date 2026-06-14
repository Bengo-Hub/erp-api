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
	"fmt"
	"strings"
	"time"

	serviceclient "github.com/Bengo-Hub/shared-service-client"
	"github.com/google/uuid"
	"go.uber.org/zap"
)

// Payout is one net-pay disbursement line. Amounts are decimal STRINGS (gaps §2.1 — no
// float across the disburse boundary).
type Payout struct {
	RecipientID   string `json:"recipient_id"`
	Amount        string `json:"amount"`
	Currency      string `json:"currency"`
	PaymentMethod string `json:"payment_method"`
	ReferenceID   string `json:"reference_id"`
	Description   string `json:"description"`
}

// Client calls treasury-api over S2S (X-API-Key: INTERNAL_SERVICE_KEY) using the shared
// service client for resilience (retry/circuit-breaker) and header propagation.
type Client struct {
	apiKey  string
	enabled bool
	sc      *serviceclient.Client
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
		enabled: enabled,
		sc:      sc,
		log:     log,
	}
}

// Enabled reports whether the client is configured for S2S calls.
func (c *Client) Enabled() bool { return c.enabled }

// Disburse POSTs the payouts to treasury. idempotencyKey is sent as Idempotency-Key so
// treasury can dedupe a re-sent batch (sprint §payroll→treasury flow). Best-effort: a
// transport/5xx failure is returned to the caller but does NOT roll back the GL event.
func (c *Client) Disburse(ctx context.Context, tenantID uuid.UUID, payouts []Payout, idempotencyKey string) error {
	if !c.enabled {
		c.log.Debug("treasury disburse skipped: client not configured")
		return nil
	}
	if len(payouts) == 0 {
		return nil
	}
	headers := map[string]string{"X-API-Key": c.apiKey}
	if idempotencyKey != "" {
		headers["Idempotency-Key"] = idempotencyKey
	}
	path := fmt.Sprintf("/api/v1/s2s/%s/payouts/disburse", tenantID.String())
	resp, err := c.sc.Post(ctx, path, map[string]any{"payouts": payouts}, headers)
	if err != nil {
		return fmt.Errorf("treasury: disburse: %w", err)
	}
	if !resp.IsSuccess() {
		return fmt.Errorf("treasury: disburse: status %d", resp.StatusCode)
	}
	return nil
}
