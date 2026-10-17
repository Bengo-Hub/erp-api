package database

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/Bengo-Hub/erp-api/internal/config"
)

// NewPool creates a pgx connection pool from the supplied Postgres config and
// applies session-level timeout guardrails.
func NewPool(ctx context.Context, cfg config.PostgresConfig) (*pgxpool.Pool, error) {
	// Pin search_path to the erp schema (isolates the service from the retired legacy
	// system's tables still in public on the same bengo_erp DB).
	poolConfig, err := pgxpool.ParseConfig(cfg.DSN())
	if err != nil {
		return nil, fmt.Errorf("postgres: parse config: %w", err)
	}

	poolConfig.MaxConns = int32(cfg.MaxOpenConns)
	poolConfig.MinConns = int32(cfg.MaxIdleConns)
	poolConfig.MaxConnLifetime = cfg.ConnMaxLifetime

	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()

	pool, err := pgxpool.NewWithConfig(ctx, poolConfig)
	if err != nil {
		return nil, fmt.Errorf("postgres: create pool: %w", err)
	}

	if cfg.StatementTimeout > 0 {
		_, _ = pool.Exec(ctx, fmt.Sprintf("SET statement_timeout = '%dms'", cfg.StatementTimeout.Milliseconds()))
	}
	if cfg.IdleInTransactionTimeout > 0 {
		_, _ = pool.Exec(ctx, fmt.Sprintf("SET idle_in_transaction_session_timeout = '%dms'", cfg.IdleInTransactionTimeout.Milliseconds()))
	}

	return pool, nil
}
