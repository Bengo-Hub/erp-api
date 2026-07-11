# KRA Statutory Payroll Report Templates — Expected Structure & Fidelity

_Last reviewed: 2026-07-11. Owner: erp-api `internal/modules/reports`._

This documents the **column/sheet structure KRA and the statutory bodies expect** for each payroll return the ERP produces, what the current exporters emit, and the remaining fidelity gaps. It is the reference for `payroll_reports.go` (data) and `docs/xlsx_generator.go` (rendering).

The reports are config-driven from `erp-ui/src/lib/reports-config.ts` (`REPORTS[]`) and produced by `reports.Service` methods, then rendered to CSV / XLSX / PDF via `docs.Generator`. Column `field` keys must match between the Go `Report.Columns` and the UI `columns[].field`.

---

## 1. P9A — Tax Deduction Card (per employee, per year)

The P9A is the **employee's** annual PAYE card. iTax expects **one row per month (Jan–Dec)** with the running statutory picture, so the canonical P9A is a 12-row grid per employee, not a single summary row.

| iTax P9A column | Meaning | Source (payslip field) |
|---|---|---|
| Month | Jan…Dec | period |
| Basic Salary | contractual basic | `basic_salary` |
| Benefits / Non-Cash | taxable benefits (car, housing, etc.) | benefit lines |
| Gross Pay | A = basic + benefits | `gross_pay` |
| E1 — 30% of A | pension-relief ceiling test | derived |
| E2 — Actual pension contribution | DB/DC scheme + NSSF | `nssf_employee_tier_1+2` (+ scheme) |
| E3 — Fixed KES 30,000/mo (20,000 pre-2024) | statutory pension cap | constant |
| **Deductible pension** = min(E1,E2,E3) | | derived |
| SHIF | 2.75% (pre-tax since Dec-2024) | `shif_or_nhif_contribution` |
| Affordable Housing Levy | 1.5% (pre-tax, Sheet M on P10) | `housing_levy` |
| Chargeable Pay | A − deductible pension − SHIF − AHL | `taxable_pay` |
| Tax Charged | PAYE on chargeable pay (bands) | `paye + tax_relief` |
| Personal Relief | 2,400/mo | `tax_relief` (personal portion) |
| Insurance Relief | 15% of premiums, cap 5,000/mo | **not yet captured** |
| PAYE Tax | Tax charged − reliefs | `paye` |

**Current fidelity:** the `P9` method emits **one summary row per employee** (annual totals) with the enriched columns `nssf, shif, housing_levy, tax_charged, personal_relief` now added (2026-07-11). The true **12-month grid** and the pension E1/E2/E3 ceiling logic are the remaining gap (needs the multi-sheet workbook + per-month payslip fan-out). Insurance relief depends on §5 (relief capture).

---

## 2. P10 / P10A — Employer Annual PAYE Return

Filed by the **employer** on iTax. The iTax P10 workbook has multiple sheets:

- **Sheet B1 — Employees with PAYE**: PIN, name, gross, pension, SHIF, AHL, chargeable, PAYE, reliefs, net.
- **Sheet B2 — Employees not subject to PAYE** (below threshold).
- **Sheet M — Affordable Housing Levy**: per-employee AHL (employee 1.5% + employer 1.5%).
- **Sheet N / others** — disability, car benefit schedules where applicable.

| P10A column (current) | field |
|---|---|
| Employee Name | `employee_name` |
| KRA PIN | `employee_pin` |
| Total Gross Pay | `total_gross_pay` |
| Total PAYE | `total_paye` |
| Total NSSF | `total_nssf` |
| Total SHIF | `total_shif` _(added 2026-07-11)_ |
| Total Housing Levy | `total_housing_levy` _(added 2026-07-11)_ |

**Current fidelity:** single-sheet employee summary with NSSF/SHIF/AHL now present. Gaps: split into Sheet B1/B2 by PAYE-liability, dedicated **Sheet M** for AHL (employer + employee halves), and monthly rather than annual granularity for the true iTax import template.

---

## 3. NSSF — SF24 / by-member schedule

NSSF (Year-4 rates, eff. Feb 2026: LEL 9,000 / UEL 108,000, Tier I + Tier II) expects a member schedule:

| Column | Source |
|---|---|
| Member Name | employee |
| NSSF No / National ID | employee |
| KRA PIN | employee |
| Tier I (on first 9,000) | `nssf_employee_tier_1` |
| Tier II (9,000–108,000) | `nssf_employee_tier_2` |
| Employee total | tier1+tier2 |
| Employer match | equal to employee | 
| Grand total | 2 × contribution |

**Current fidelity:** NSSF report emits employee tiers. Employer-match column and the official SF24 layout are pending.

---

## 4. SHIF (SHA) — by-member contribution schedule

SHIF replaced NHIF (2.75% of gross, no cap, min 300). SHA expects member name, SHA/national ID, gross, 2.75% contribution. Sourced from `shif_or_nhif_contribution`. Byproduct of the P10 data set.

---

## 5. Reliefs not yet captured (blocks full P9A/PAYE fidelity)

`payrollengine.applyPAYE` currently applies **personal relief only** (2,400/mo). KRA allows these additional credits that reduce PAYE:

- **Insurance relief** — 15% of life/health/education premiums, cap **5,000/mo (60,000/yr)**.
- **Pension/provident relief** — deductible pension is pre-tax, min(30% gross, actual, 30,000/mo).
- **Affordable Housing relief** — 15% of AHL, where the AHL is not already treated as a deduction (post-2024 it is a pre-tax deduction, so relief no longer double-counts).
- **Post-retirement medical fund** — 15%, cap 60,000/yr.
- **Disability exemption** — first 150,000/mo exempt with an ADP exemption certificate.

To capture these the engine needs per-employee relief inputs (schema + employee-form fields), threaded through `buildEmployeeInput` → `EmployeeInput` → `applyPAYE`. This is the highest-value remaining fidelity work; until then P9A insurance-relief and disability columns stay blank.

---

## 6. Filing ownership (recap)

The ERP **produces portal-ready files**; actual submission is on **iTax** (P10/P9A), the **NSSF portal** (SF24), and the **SHA portal** (SHIF). There is no KRA API that files PAYE — the M-Pesa Tax Remittance / PRN path only *pays* an assessed liability, it does not file the return. See treasury `docs/tax-and-compliance.md` §4a for the cross-service matrix.
