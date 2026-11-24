# Kenyan statutory payroll rates (2024 to 2025 changes)

Reference for the national rate set that `cmd/seed-payroll` writes under the system tenant and that
`internal/modules/payroll/payrollengine` applies. The authoritative values live in
`payrollengine.KRADefaults()`; a golden-master test pins gross 100,000 to net 71,617.65.

## Rates

### PAYE (February 2025 onwards)
| Band | Monthly income (KES) | Rate |
|---|---|---|
| 1 | 0 to 24,000 | 10% |
| 2 | 24,001 to 32,333 | 25% |
| 3 | 32,334 to 500,000 | 30% |
| 4 | 500,001 to 799,999 | 32.5% |
| 5 | 800,000 and above | 35% |

Personal relief: KES 2,400 per month, the only relief that remains.

### NSSF (Year 4 limits, 1 February 2026 onwards)
- Lower earnings limit KES 9,000 and upper earnings limit KES 108,000, 6% employee matched 100% by
  the employer.
- Tier 1: 6% of pensionable pay up to KES 9,000, at most KES 540.
- Tier 2: 6% of pensionable pay from KES 9,001 to 108,000, at most KES 5,940.
- Maximum KES 6,480 for the employee and the same for the employer.

### SHIF (October 2024 onwards)
- 2.75% of gross salary, minimum KES 300 per month. It replaced NHIF; the engine still supports NHIF
  for periods before the configured cutover.

### Housing Levy (March 2024 onwards)
- 1.5% of gross salary, matched 100% by the employer.

### Relief repeals (December 2024)
- The 15% relief on SHIF and on the Housing Levy was repealed. Personal relief stays.

## How the Go service applies them

- Rates are effective-dated rows in `payrollsettings` (formula, items, reliefs). The formula chosen for
  a payroll month is the one effective on that date; a tenant without its own current formula inherits
  the system tenant's. An unconfigured statutory line is an error, never a silent zero.
- Repealed reliefs are marked inactive, so a period after the repeal yields zero relief for them.
- Formula endpoints: `GET /formulas`, `GET /formulas/{id}`, `POST /formulas`, `PUT /formulas/{id}`,
  `GET /formulas/relief-status` and `POST /formula-management`, under the payroll settings route.
- To change a rate: add a new effective-dated formula (do not edit a past one), update
  `KRADefaults()` and its test, and re-run `go run ./cmd/seed-payroll` (idempotent; it skips types that
  already have a formula under the system tenant).
