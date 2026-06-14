// Package treasury is a service-to-service client for treasury-api. erp-api uses it only
// to request payroll net-pay disbursement (POST /s2s/{tenant}/payouts/disburse). Treasury
// remains the single source of truth for money movement + GL; erp-api never posts ledgers.
package treasury

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

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

// Client calls treasury-api over S2S (X-API-Key: INTERNAL_SERVICE_KEY).
type Client struct {
	baseURL string
	apiKey  string
	http    *http.Client
	log     *zap.Logger
}

// NewClient builds the treasury S2S client.
func NewClient(baseURL, apiKey string, log *zap.Logger) *Client {
	return &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		apiKey:  apiKey,
		http:    &http.Client{Timeout: 12 * time.Second},
		log:     log.Named("treasury.client"),
	}
}

// Enabled reports whether the client is configured for S2S calls.
func (c *Client) Enabled() bool { return c.baseURL != "" && c.apiKey != "" }

// Disburse POSTs the payouts to treasury. idempotencyKey is sent as Idempotency-Key so
// treasury can dedupe a re-sent batch (sprint §payroll→treasury flow). Best-effort: a
// transport/5xx failure is returned to the caller but does NOT roll back the GL event.
func (c *Client) Disburse(ctx context.Context, tenantID uuid.UUID, payouts []Payout, idempotencyKey string) error {
	if !c.Enabled() {
		c.log.Debug("treasury disburse skipped: client not configured")
		return nil
	}
	if len(payouts) == 0 {
		return nil
	}
	body, err := json.Marshal(map[string]any{"payouts": payouts})
	if err != nil {
		return fmt.Errorf("treasury: marshal payouts: %w", err)
	}
	url := fmt.Sprintf("%s/api/v1/s2s/%s/payouts/disburse", c.baseURL, tenantID.String())
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", c.apiKey)
	if idempotencyKey != "" {
		req.Header.Set("Idempotency-Key", idempotencyKey)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("treasury: disburse: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("treasury: disburse: status %d", resp.StatusCode)
	}
	return nil
}
