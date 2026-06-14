// Package fx implements FX (foreign-exchange) rate fetching + storage (Go replacement for
// the Django integrations.tasks.fetch_exchange_rates Celery Beat job). Rates are written to
// the exchange_rates table; the provider API key is sourced from the secret store via the
// ExchangeRateAPISettings.api_key_ref env-var name (NOT a DB ciphertext — fixes gaps §1.1/2).
package fx

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"

	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/exchangerate"
	"github.com/Bengo-Hub/erp-api/internal/ent/exchangerateapisettings"
)

// Service fetches + persists FX rates. Tenant-scoped settings drive each fetch.
type Service struct {
	orm  *ent.Client
	http *http.Client
	log  *zap.Logger
}

func NewService(orm *ent.Client, log *zap.Logger) *Service {
	return &Service{orm: orm, http: &http.Client{Timeout: 12 * time.Second}, log: log.Named("fx")}
}

// ListRates returns stored rates for a base currency (most recent first).
func (s *Service) ListRates(ctx context.Context, base string) ([]*ent.ExchangeRate, error) {
	q := s.orm.ExchangeRate.Query()
	if base != "" {
		q = q.Where(exchangerate.BaseCurrency(base))
	}
	return q.Order(ent.Desc(exchangerate.FieldRateDate)).Limit(500).All(ctx)
}

// FetchAllActive fetches rates for every tenant with active FX settings. Returns the number
// of rate rows upserted. Best-effort per tenant (one failure doesn't abort the rest).
func (s *Service) FetchAllActive(ctx context.Context) (int, error) {
	settings, err := s.orm.ExchangeRateAPISettings.Query().
		Where(exchangerateapisettings.IsActive(true)).All(ctx)
	if err != nil {
		return 0, fmt.Errorf("fx: load settings: %w", err)
	}
	total := 0
	for _, st := range settings {
		n, ferr := s.fetchForSettings(ctx, st)
		if ferr != nil {
			s.log.Warn("fx fetch failed for tenant", zap.String("tenant", st.TenantID.String()), zap.Error(ferr))
			continue
		}
		total += n
	}
	return total, nil
}

// exchangeRateAPIResponse is the exchangerate-api.com /v6/{key}/latest/{base} shape.
type exchangeRateAPIResponse struct {
	Result          string             `json:"result"`
	BaseCode        string             `json:"base_code"`
	ConversionRates map[string]float64 `json:"conversion_rates"`
}

func (s *Service) fetchForSettings(ctx context.Context, st *ent.ExchangeRateAPISettings) (int, error) {
	apiKey := ""
	if st.APIKeyRef != "" {
		apiKey = os.Getenv(st.APIKeyRef) // secret store lookup by env-var name
	}
	if apiKey == "" {
		return 0, fmt.Errorf("fx: no API key resolved from ref %q", st.APIKeyRef)
	}
	base := st.BaseCurrency
	if base == "" {
		base = "KES"
	}
	url := fmt.Sprintf("https://v6.exchangerate-api.com/v6/%s/latest/%s", apiKey, base)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	resp, err := s.http.Do(req)
	if err != nil {
		return 0, fmt.Errorf("fx: fetch: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return 0, fmt.Errorf("fx: provider status %d", resp.StatusCode)
	}
	var body exchangeRateAPIResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return 0, fmt.Errorf("fx: decode: %w", err)
	}
	today := time.Now().UTC().Truncate(24 * time.Hour)
	n := 0
	for quote, rate := range body.ConversionRates {
		if quote == base {
			continue
		}
		if err := s.upsertRate(ctx, base, quote, decimal.NewFromFloat(rate), today, st.Provider); err != nil {
			s.log.Warn("fx upsert failed", zap.String("quote", quote), zap.Error(err))
			continue
		}
		n++
	}
	_, _ = st.Update().SetLastFetchedAt(time.Now().UTC()).Save(ctx)
	return n, nil
}

// upsertRate inserts or updates the unique (base, quote, date) rate row.
func (s *Service) upsertRate(ctx context.Context, base, quote string, rate decimal.Decimal, date time.Time, source string) error {
	existing, err := s.orm.ExchangeRate.Query().Where(
		exchangerate.BaseCurrency(base),
		exchangerate.QuoteCurrency(quote),
		exchangerate.RateDate(date),
	).Only(ctx)
	if ent.IsNotFound(err) {
		_, cerr := s.orm.ExchangeRate.Create().
			SetBaseCurrency(base).SetQuoteCurrency(quote).SetRate(rate).
			SetRateDate(date).SetSource(source).Save(ctx)
		return cerr
	}
	if err != nil {
		return err
	}
	_, uerr := existing.Update().SetRate(rate).SetSource(source).Save(ctx)
	return uerr
}
