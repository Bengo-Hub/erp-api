# Payroll settings: platform defaults, tenant choices

Payroll configuration is defined once at platform level and every organisation inherits it. An
organisation changes only what it needs, and that change stays its own. Nothing is copied per
tenant except the one item a tenant chooses to customise.

The platform rows belong to the synthetic system tenant `PAYROLL_SYSTEM_TENANT_ID` (default
`00000000-0000-0000-0000-0000000005ff`). All resolution goes through `internal/modules/payrollsettings`;
the settings screens, the payroll engine config, payslip lines and statutory reports use the same
resolver, so what an organisation sees is what its payroll computes.

## What is inherited and how a tenant changes it

| Setting | Platform rows | Tenant change | Stored as |
|---|---|---|---|
| Statutory formulas (PAYE primary and secondary, NSSF, SHIF, NHIF, Housing Levy, NITA) | `payroll_formulas` + bands + split under the system tenant | **Customise** copies that one formula (row, bands, split) to the tenant; **Revert** deletes the tenant's versions | Tenant formula rows for that `(type, category)` |
| KRA reliefs (personal, insurance, affordable housing, disability, pension, mortgage interest) | `payroll_reliefs` under the system tenant | Switch on or off, or set own amounts; **Revert** removes the tenant row | A tenant relief row with the same title. A row with zero limit and zero percentage is an on/off choice only and keeps the platform amounts |
| Earnings, deductions, benefits | `payroll_components` catalogue under the system tenant, code in `wb_code` | Switch on or off, or set own title, amount and rates; **Revert** drops the choice | One JSON record per tenant in `app_settings` key `payroll.components`, keyed by component code |
| Statutory on/off (PAYE, NSSF, SHIF, Housing Levy, NITA) | On for everyone | Tax & Statutory tab or the switch on the statutory component | `general_hr_settings` toggles (tenant row only, never inherited) |

A tenant may still create its own components and formulas; they show as **Own**. A tenant component
with the same code or title as a platform component replaces it in the tenant's list.

## Resolution rules

**Formulas.** For a payroll month the resolver picks, in order: the tenant's version in force that
month, the platform version in force that month, the tenant's current version, the platform's
current version. A version is in force from its `effective_from`; a superseded version only covers
its closed window (`effective_from` to `effective_to`), so re-running an earlier month uses the rates
of that month. Saving a new current version closes the previous one the day before its start. A
missing required formula still fails the run (no silent zero).

**Components.** Statutory components are on by default and follow the tenant's statutory toggles.
Module-managed components (basic pay, overtime, holiday work, piece work, expense claims, loans,
advances, losses and damages, staff purchases) are on: their amounts and lines come from their own
approved records. Every other component is opt-in. A benefit assigned to a component the tenant has
switched off is not paid. A platform component the platform owner switched off is off for everyone.

**Per-employee earnings and deductions.** A component the organisation has switched on (not
statutory and not driven by its own module) can be given to individual employees on the employee
page, tab **Earnings and deductions**. Each assignment is an `employee_benefits` row (the table the
legacy system used for per-employee benefits) with `component_id`, `amount`, `effective_date` and
`end_date` (first day of the start and end months), `is_active`, and `metadata` holding
`percentage`, `percent_of` (`basic` or `gross`) and `reference` (the scheme, membership or policy
number). HELB, SACCO, union dues, pension, provident fund, insurance premium and court orders need a
reference (`reference_label` on the component says which number). A payroll run applies them as follows:

- Only assignments whose months cover the period, on components still switched on. Switching a
  component off stops it for every employee it was assigned to; the assignment is kept and shows as
  switched off.
- Amount: the assignment's own percentage or amount, else the component's default amount, else its
  default rate. A percentage applies to basic pay, or to gross pay (basic plus the fixed and
  basic-based earnings assigned) when `percent_of` is `gross`.
- Earnings: a taxable component is a taxable allowance (gross, NSSF, SHIF, Housing Levy and PAYE); a
  non-taxable one (per diem) adds to gross and net pay only.
- Deductions come off after the statutory deductions, PAYE and the recoverables (loans, advances,
  losses, staff purchases), in the deduction order's phase and then component priority. They are
  listed and totalled with the non-statutory deductions. Pension and provident fund count towards
  the pension relief and an insurance premium towards the insurance relief; when the salary tab
  records the same contribution the larger figure counts, not the sum. Relief follows the assigned
  amount even when net pay could not cover all of it. Only these codes change PAYE.
- Rule for a deduction larger than net pay: it is capped at the net pay left and the remainder is
  reported (`DeductionShortfall` on the run result, `deduction_shortfall` in the preview, and
  a `deduction_shortfall` payslip line that no total counts); it is not carried forward. The engine has no cap for
  loans (they can still take net pay below zero, unchanged), so these deductions never take
  anything from a loan or advance recovery.
- Payslip lines carry the component title the organisation sees and its `component_id`.

Endpoints: `GET|POST /employees/{employeeId}/components`, `PUT|DELETE
/employees/{employeeId}/components/{id}` (view needs `hrm.payroll.view`, changes `hrm.payroll.manage`).
Each component in `GET /payroll-components` carries `assignable` and `reference_label`.

**SHIF minimum.** SHIF is 2.75% of gross with a KES 300 monthly minimum. A band cannot express a
floor, so the minimum is `metadata.minimum_contribution` on the platform SHIF formula and the engine
charges it whenever there is pay (`FormulaRates.MinimumContribution`). It is inherited like the rest:
a tenant that customises SHIF gets the minimum on its copy, a tenant version that records none (an
older copy) uses the platform's, and a platform change reaches every tenant that records none. `cmd/seed-payroll` sets 300 on platform SHIF versions that record no
minimum and leaves a recorded value alone (zero included). The formula editor shows it as **Minimum
Monthly Contribution**; `minimum_contribution` on the formula endpoints (omitted on update keeps it).

**Reliefs.** Personal and insurance relief are statutory and on by default. Switching Personal
Relief off removes it from PAYE for that tenant only.

## Who can change what

- Tenant payroll managers: switch components and reliefs on or off, customise and revert.
- Platform owner: editing a platform formula or component changes it for every tenant that has not
  customised that item. `?scope=platform` on the settings endpoints reads and writes the platform
  rows directly. A current platform formula and statutory platform components cannot be deleted.

## Endpoints (under `/api/v1/hrm/payroll-settings`)

- `GET /payroll-components?category=Earnings|Deductions|Benefits[&active=true]`: resolved list with
  `source` (`platform` or `tenant`), `is_platform`, `customised`, `opt_in`, `statutory`, `managed_by`.
- `PUT /payroll-components/{id}`: on a platform component this saves the tenant's own values.
- `POST /payroll-components/{id}/activation` `{"is_active": true}` and `POST /payroll-components/{id}/revert`.
- `GET /formulas`: tenant rows plus every platform formula the tenant has not customised, each with
  `source` and, on tenant rows, `overrides_id`.
- `POST /formulas/{id}/customise`, `POST /formulas/{id}/revert`, `DELETE /formulas/{id}` (own rows).
- `GET /formulas/reliefs`, `GET /formulas/relief-status?relief_type=personal_relief`,
  `POST /formula-management` with `update_relief` or `revert_relief`.
- `POST /platform/treasury-rate-sync`: platform owner, applies treasury's approved rates now.

## Seeding

`cmd/seed-payroll` (every deploy, idempotent) seeds the platform formulas from
`payrollengine.KRADefaults()`, the reliefs, the component catalogue (`payrollsettings.PlatformCatalogue`)
and then runs the treasury rate sync. `cmd/seed-defaults` no longer copies reliefs per tenant and
removes tenant relief rows that repeat the platform relief exactly.

## Treasury rate sync

treasury-api owns the platform-wide Kenya statutory rate reference (`statutory_rates`). A rate enters
it when the platform owner creates it or approves a tax advisor proposal, and
`GET /api/v1/s2s/{tenant}/statutory-rates` lists the rates in force. erp-api reads that list on every
deploy and on demand, maps PAYE bands and personal relief, NSSF tiers, SHIF and the Housing Levy onto
the platform formulas, and applies a change only when treasury's set is newer (later effective date)
and different. The change becomes a new current platform version from treasury's date; tenant
versions are never touched. Treasury does not publish SHIF's minimum contribution, so a synced SHIF
version keeps the minimum of the version it replaces (see "SHIF minimum" below).

Treasury publishes no event when a rate is approved, so the sync pulls. The proposed event contract
for treasury is `treasury.statutory_rate.approved` with `{category, code, rate, rate_type,
threshold_min, threshold_max, effective_from, effective_to, proposal_id, verified_at}`; erp-api would
consume it through the shared-events outbox like `treasury.claim.settled` and run the same sync.
