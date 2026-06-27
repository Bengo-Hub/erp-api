// Command seed-contracts back-fills employment contracts for existing employees that have none.
//
// Per the 2026-06 decision (all employment types): permanent/unspecified -> indefinite
// (no end date); contract/fixed-term -> a 12-month term; casual -> open (no end);
// intern/probation -> a 6-month term. Salary is taken from the employee's salary_details.
// Start date defaults to the start of the current year (override via CONTRACT_START=YYYY-MM-DD).
//
// Idempotent: an employee that already has an ACTIVE contract is skipped. Optionally scope to a
// single tenant with TENANT_SLUG=<slug> (default: every tenant shadow).
//
// Usage:
//
//	POSTGRES_MIGRATE_URL=postgres://... TENANT_SLUG=mss go run ./cmd/seed-contracts
package main

import (
	"context"
	"database/sql"
	"log"
	"os"
	"time"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/joho/godotenv"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/authtenant"
	"github.com/Bengo-Hub/erp-api/internal/ent/contract"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
)

func main() {
	_ = godotenv.Load()
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("load config: %v", err)
	}
	dsn := cfg.Postgres.MigrateDSN()
	if dsn == "" {
		dsn = "postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable"
	}
	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	defer func() { _ = sqlDB.Close() }()

	client := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, sqlDB)))
	defer func() { _ = client.Close() }()
	ctx := context.Background()

	start := time.Date(time.Now().UTC().Year(), 1, 1, 0, 0, 0, 0, time.UTC)
	if s := os.Getenv("CONTRACT_START"); s != "" {
		if d, derr := time.Parse("2006-01-02", s); derr == nil {
			start = d
		} else {
			log.Fatalf("invalid CONTRACT_START %q (want YYYY-MM-DD): %v", s, derr)
		}
	}

	q := client.AuthTenant.Query()
	if slug := os.Getenv("TENANT_SLUG"); slug != "" {
		q = q.Where(authtenant.Slug(slug))
	}
	tenants, err := q.All(ctx)
	if err != nil {
		log.Fatalf("list tenants: %v", err)
	}
	if len(tenants) == 0 {
		log.Println("seed-contracts: no matching tenants — nothing to seed")
		return
	}

	total := 0
	for _, t := range tenants {
		n, err := seedTenant(ctx, client, t.ID, start)
		if err != nil {
			log.Fatalf("seed-contracts: tenant %s (%s): %v", t.Slug, t.ID, err)
		}
		total += n
		log.Printf("seed-contracts: tenant %s — created %d contracts", t.Slug, n)
	}
	log.Printf("seed-contracts: done (%d contracts across %d tenants)", total, len(tenants))
}

// seedTenant creates a contract for every active employee in the tenant that lacks one.
func seedTenant(ctx context.Context, client *ent.Client, tenantID uuid.UUID, start time.Time) (int, error) {
	emps, err := client.Employee.Query().
		Where(employee.TenantID(tenantID), employee.Terminated(false), employee.Deleted(false)).
		All(ctx)
	if err != nil {
		return 0, err
	}
	created := 0
	for _, e := range emps {
		// Skip if an active contract already exists (idempotent).
		exists, err := client.Contract.Query().
			Where(contract.TenantID(tenantID), contract.EmployeeID(e.ID), contract.Status("active")).
			Exist(ctx)
		if err != nil {
			return created, err
		}
		if exists {
			continue
		}

		empType := employmentType(ctx, client, tenantID, e.ID)
		ctype, end := contractTerms(empType, start)
		salary := monthlySalary(ctx, client, tenantID, e.ID)

		b := client.Contract.Create().
			SetTenantID(tenantID).
			SetEmployeeID(e.ID).
			SetContractType(ctype).
			SetStartDate(start).
			SetSalary(salary).
			SetStatus("active")
		if end != nil {
			b = b.SetEndDate(*end)
			months := int(end.Sub(start).Hours() / 24 / 30)
			if months > 0 {
				b = b.SetDurationMonths(months)
			}
		}
		if _, err := b.Save(ctx); err != nil {
			return created, err
		}
		created++
	}
	return created, nil
}

// contractTerms maps an employment type to a contract_type + optional end date.
func contractTerms(empType string, start time.Time) (string, *time.Time) {
	switch empType {
	case "contract", "fixed-term", "fixed_term":
		end := start.AddDate(1, 0, 0)
		return "fixed-term", &end
	case "intern", "probation":
		end := start.AddDate(0, 6, 0)
		return empType, &end
	case "casual":
		return "casual", nil // open-ended; casuals are paid via the casual module, not PAYE
	default: // permanent / unspecified -> indefinite
		return "permanent", nil
	}
}

func employmentType(ctx context.Context, client *ent.Client, tenantID, empID uuid.UUID) string {
	hr, err := client.HRDetails.Query().
		Where(hrdetails.TenantID(tenantID), hrdetails.EmployeeID(empID)).First(ctx)
	if err != nil || hr.EmploymentType == "" {
		return "permanent"
	}
	return hr.EmploymentType
}

func monthlySalary(ctx context.Context, client *ent.Client, tenantID, empID uuid.UUID) decimal.Decimal {
	sd, err := client.SalaryDetails.Query().
		Where(salarydetails.TenantID(tenantID), salarydetails.EmployeeID(empID)).First(ctx)
	if err != nil {
		return decimal.Zero
	}
	return sd.MonthlySalary
}
