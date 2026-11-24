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
| 4 | 500,001 to 800,000 | 32.5% |
| 5 | Above 800,000 | 35% |

Months up to November 2026 keep the earlier platform limit of 799,999 for band 4 when re-run; the
corrected version applies from the December 2026 payroll (`payrollsettings.EnsurePAYEBand4`).

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
  a payroll month is the one in force on that date: the tenant's own version first, then the platform
  version (the system tenant's). An unconfigured statutory line is an error, never a silent zero. The
  full inherit and customise model is in [payroll-settings.md](payroll-settings.md).
- Repealed reliefs are marked inactive, so a period after the repeal yields zero relief for them.
  Reliefs are platform rows too; a tenant only records its own on/off choice.
- Formula endpoints: `GET /formulas`, `GET /formulas/{id}`, `POST /formulas`, `PUT /formulas/{id}`,
  `DELETE /formulas/{id}`, `POST /formulas/{id}/customise`, `POST /formulas/{id}/revert`,
  `GET /formulas/reliefs`, `GET /formulas/relief-status` and `POST /formula-management`, under the
  payroll settings route.
- To change a rate: approve it in treasury (the deploy-time sync, or `POST /platform/treasury-rate-sync`,
  writes it as a new platform version), or as platform owner save a new current version of the
  platform formula with its effective date. The previous version is closed the day before, so earlier
  months keep their rates. Update `KRADefaults()` and its test only when the golden master changes.
