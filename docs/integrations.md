# erp-api Integrations

> Every external interaction of `erp-api`: NATS subjects (pub/sub), S2S HTTP calls
> (inbound + outbound), SSO/OIDC, subscription gating, notifications, treasury payroll/GL,
> exchange-rate API, branding. Authoritative for the Go revamp — keep contracts identical.
> (Supersedes the old pre-decomposition integration guide.)

Go code: `internal/platform/{events,auth,treasury,cache}`, `internal/modules/consumers`,
`internal/services/usersync`, `internal/modules/fx`, shared-auth-client middleware. (The
Django paths below are retained as the contract reference — the Go rebuild keeps the same
subjects + S2S contracts.)

---

## 0. VERIFIED INTEGRATION MAP (authoritative — plan §0a-map, audited across siblings)

ERP's **entire** cross-service surface. ERP consumes ONLY these and owns no other service's
data. ERP = client only for all of them.

- **auth-service (SSO)** — JWT/JWKS validation + `/auth/me` (shared-auth-client). Branding
  read-through `GET /api/v1/tenants/by-slug/{slug}` (auth-api public route), Redis-cached 6h
  via `internal/platform/auth.BrandingClient` → surfaced on the public branding endpoint.
  Tenant/outlet shadows synced from `auth.tenant.*` / `auth.outlet.created|updated` events.
- **treasury (finance-service)** — payroll disbursement `POST /api/v1/s2s/{tenant}/payouts/disburse`
  (`internal/platform/treasury`); ERP publishes `erp.payroll.processed` (treasury posts the GL
  journal) and consumes `treasury.payroll.disbursed` to mark payslips published/paid. **Payroll
  tax stays ERP-owned**; treasury owns GL + payout rails + bank/payment reference.
- **notifications-service** — ERP publishes `erp.email.requested` (supports base64 attachments,
  e.g. payslip PDFs) + `erp.notification.requested` (`internal/platform/events.Notifications`);
  notifications-api consumes both. **ERP never sends email/SMS directly.**
- **subscriptions-service** — feature gating via the tenant subscription endpoint
  (`/api/v1/tenants/{id}/subscription`, Redis-cached), **mutations-only**. Single shared
  `INTERNAL_SERVICE_KEY` for all S2S.
- **NO consumption from inventory / ordering / logistics / marketflow / projects.** Assets →
  inventory+treasury, customers → marketflow, orders/address_book/pickup_station/service_type →
  ordering, projects/tenders → projects-service, banks → treasury/payment-rail reference. ERP
  links to those only via UI menu (external), never their data/schemas.
- **Shared libs:** shared-auth-client, shared-events (outbox + QueueSubscribe + IdempotencyStore),
  httpware, cache, shared-service-client.

---

## 1. Event bus (NATS JetStream + transactional outbox)

### Envelope (`integrations/events.py:_envelope`)
```json
{
  "id": "<uuid>",
  "tenant_id": "<auth-api tenant uuid>",
  "aggregate_type": "erp",
  "aggregate_id": "<batch/object ref>",
  "event_type": "payroll.processed",
  "payload": { },
  "timestamp": "<iso8601>",
  "version": "1.0",
  "source": "erp"
}
```
Subject = `{aggregate_type}.{event_type}` (e.g. `erp.payroll.processed`).
All publishing/consuming gated by `EVENTS_ENABLED`. Drained by `manage.py drain_outbox`,
consumed by `manage.py consume_events`.

### Subjects PUBLISHED by erp-api

| Subject | Emitted by | Payload shape (key fields) | Consumed by |
|---|---|---|---|
| `erp.payroll.processed` | `hrm/payroll/treasury_integration.py:publish_and_disburse` | `{tenant_id, outlet_id, period, currency:"KES", totals:{gross,deductions,net}, lines:[{employee_id, employee_ref, gross, net_pay, statutory:{paye,nhif,nssf,housing}}], cost_center, batch_ref}` | treasury-api (posts GL: DR Salaries & Wages, CR Accrued Salary Payable + statutory liabilities) |
| `erp.email.requested` | `integrations/notifications_client.py:EmailService.send_email` | `{subject, message, recipient_list[], html_message, from_email, cc[], bcc[], reply_to, attachments[{filename,content(base64),mimetype,encoding}]}` | notifications-api |
| `erp.notification.requested` | `integrations/notifications_client.py:NotificationService.send_notification` | `{user_id, email, title, message, notification_type, channels[], data{}, image_url, action_url, email_subject, templates:{email,sms,push}, context{}}` | notifications-api |

> Additional `erp.*` subjects can be emitted by any module via `publish_event(...)`. As of audit,
> only the three above are wired. Payslip emailing and payroll notifications both flow through
> `erp.email.requested` / `erp.notification.requested`.

### Subjects CONSUMED by erp-api

Handlers registered into `integrations.events.CONSUMER_HANDLERS` by modules.

| Subject(s) | Handler | Effect |
|---|---|---|
| `auth.tenant.*` (created/updated/…) | `integrations/tenant_sync.py:handle_tenant_event` | upsert `AuthTenant` shadow |
| `auth.outlet.*` (created/updated/archived) | `integrations/tenant_sync.py:handle_outlet_event` | upsert/archive `AuthOutlet` shadow |
| `treasury.payroll.disbursed` | `hrm/payroll/treasury_integration.py:handle_payroll_disbursed` | mark the period's payslips `published=True` (tenant-isolated by `employee__organisation__tenant_id`) |

> **Gotcha**: `CONSUMER_HANDLERS` is populated lazily by module imports; if a module isn't imported,
> its consumer silently does nothing and `consume_events` warns "No consumer handlers registered".
> (See `gaps-and-bugs.md`.)

---

## 2. Service-to-service (S2S) HTTP

Client: `integrations/service_client.py:ServiceClient` / `get_client(service, request=)`.
- Auth headers: `X-API-Key: INTERNAL_SERVICE_KEY`; forwards caller `Authorization: Bearer <jwt>`
  and `X-Tenant-ID` / `X-Tenant-Slug` / `X-Outlet-ID` from `request.auth_claims`.
- Retry: `urllib3 Retry` total=`SERVICE_CLIENT_RETRIES` (2), backoff 0.3, on 502/503/504.
- Base URLs from `settings.SERVICE_URLS` (auth, treasury, inventory, pos, ordering, notifications,
  marketflow, subscriptions).

### OUTBOUND calls erp-api makes

| Target | Method + Path | Caller | Purpose |
|---|---|---|---|
| auth-api | `GET /api/v1/tenants/by-slug/{slug}` | `tenant_sync.ensure_tenant`, `branding.get_tenant_branding` | resolve tenant UUID + branding (logo/colors/KRA/address) |
| auth-api | `GET /api/v1/tenants/{slug}/outlets` | `tenant_sync.sync_outlets` | list outlets to mirror |
| auth-api | `GET /.well-known/jwks.json` | `authmanagement/sso.py` (PyJWKClient) | RS256 public keys for JWT validation |
| treasury-api | `GET /api/v1/s2s/{tenant}/taxes` | `integrations/taxes.py:get_tax_codes` | tenant tax codes (cached 1h) |
| treasury-api | `GET /api/v1/s2s/{tenant}/taxes/{code}` | `integrations/taxes.py:get_tax_code` | single tax code |
| treasury-api | `POST /api/v1/s2s/{tenant}/payouts/disburse` | `hrm/payroll/treasury_integration.py:publish_and_disburse` | disburse net pay; body `{payouts:[{recipient_id, amount, currency:"KES", payment_method:"bank_transfer", reference_id, description}]}` |

### INBOUND endpoints other services call on erp-api

erp-api currently exposes NO dedicated `/api/v1/s2s/...` surface (HR data is not consumed S2S by
others as of audit). Inbound integration is event-driven (`auth.*`, `treasury.payroll.disbursed`).
Public/health endpoints:

| Path | Auth | Purpose |
|---|---|---|
| `GET /api/v1/core/health/` | none | liveness/readiness (Docker/k8s) |
| `GET /api/v1/integrations/health/` | none | integration subsystem health |
| `GET /api/v1/business/public-branding/` | none | public branding for login page |
| `GET /api/v1/auth/me/` | JWT | service RBAC profile (Trinity two-step) |

> Revamp note: if other services later need HR data (e.g. employee directory), add a versioned
> `/api/v1/s2s/{tenant}/...` surface guarded by `INTERNAL_SERVICE_KEY` (httpware API-key auth).

---

## 3. SSO / OIDC (auth-api as IdP)

- `SSO_ENABLED` gates the whole flow. `authmanagement/sso.py`:
  - `validate_token(jwt)` → JWKS RS256, requires `exp`+`sub`, optional `aud`/`iss`, leeway
    `AUTH_JWT_LEEWAY` (30s). JWKS cached `AUTH_JWKS_TTL` (600s).
  - `Claims` wrapper exposes: `sub, email, first/last_name, tenant_id, tenant_slug, outlet_id,
    outlet_code, outlet_use_case, is_hq_user, roles[], permissions[], is_platform_owner,
    is_superuser, sub_status, sub_features[], sub_limits{}, sub_expires, billing_mode, is_demo`.
  - `get_or_provision_user(claims)` JIT-creates/links `CustomUser` by `external_id` then email;
    sets unusable password; mirrors superuser/platform flags; assigns service roles
    (`_assign_service_roles`: 1:1 name match to ERP groups, else generic fallback, else `staff`).
- Middleware (`authmanagement/sso_middleware.py`):
  - `SSOAuthenticationMiddleware` → `request.auth_claims`.
  - `TenantOutletContextMiddleware` → `request.tenant_id` (platform-owner `?tenantId=` override),
    `request.outlet_id`, JIT tenant/outlet shadow sync.
- **Gotchas** (carry into Go): GET requests should not be blocked when claims are missing (public
  routes); the OIDC token-endpoint / GET-auth-skip behavior is the documented source of spurious
  401/403 in sibling services.

### SSO login sequence

```mermaid
sequenceDiagram
  participant UI as erp-ui
  participant AUTH as auth-api (SSO)
  participant ERP as erp-api
  UI->>AUTH: login -> RS256 JWT (tenant/outlet/roles/sub_* claims)
  UI->>ERP: GET /api/v1/... (Authorization: Bearer JWT)
  ERP->>AUTH: GET /.well-known/jwks.json (cached)
  ERP->>ERP: validate JWT, JIT-provision CustomUser shadow
  ERP->>AUTH: GET /tenants/by-slug/{slug} (JIT tenant shadow, if missing)
  UI->>ERP: GET /api/v1/auth/me/ (service roles + permissions)
  ERP-->>UI: merged identity + ERP RBAC
```

---

## 4. Subscription gating

- `authmanagement/sso_middleware.py:SubscriptionGatingMiddleware` (gated by
  `SUBSCRIPTION_GATING_ENABLED`).
- **Mutations only**: GET/HEAD/OPTIONS/TRACE always pass. Exempt prefixes: `/health`,
  `/api/v1/auth/`, `/api/v1/webhooks/`, `/swagger`, `/redoc`, `/static/`, `/media/`.
- Pass if `is_superuser || is_platform_owner || claims.is_subscription_active()`.
  `is_subscription_active()`: `billing_mode=="service_charge"` or `is_demo` → always active;
  absent `sub_status` → active (non-gated tenants); else `sub_status ∈ {ACTIVE,TRIAL,TRIALING}`.
- Block → `403 {error, code:"subscription_inactive", upgrade:true}`.
- Feature checks: `claims.has_feature(code)` against `sub_features` baked into JWT by auth-api.

---

## 5. Notifications (notifications-api via events)

The ERP owns no templates/providers. `integrations/notifications_client.py` provides drop-in
`EmailService` / `NotificationService` that publish `erp.email.requested` /
`erp.notification.requested`. Attachments are base64-normalized. Best-effort; never raises on
transport problems (durably enqueued in the outbox).

---

## 6. Treasury (payroll GL + disbursement)

`hrm/payroll/treasury_integration.py`. On payroll finalisation:
1. `publish_event("payroll.processed", event, aggregate_id=batch_ref, tenant_id=...)` →
   treasury posts the GL journal (DR Salaries & Wages; CR Accrued Salary Payable + PAYE/NHIF/NSSF/
   Housing-Levy liabilities).
2. `POST /api/v1/s2s/{tenant}/payouts/disburse` with per-employee net-pay payouts (best-effort;
   transport failure does not roll back the GL event — treasury reconciles).
3. Consume `treasury.payroll.disbursed` → mark payslips `published`.

Treasury is the single source of truth for money + GL; the ERP never posts ledgers or moves cash.

### Payroll → treasury sequence

```mermaid
sequenceDiagram
  participant ERP as erp-api
  participant OB as EventOutbox
  participant NATS
  participant TREAS as treasury-api
  ERP->>OB: publish_event(erp.payroll.processed)  (in DB txn)
  ERP->>TREAS: POST /s2s/{tenant}/payouts/disburse {payouts[]}
  OB-->>NATS: drain_outbox -> erp.payroll.processed
  NATS-->>TREAS: erp.payroll.processed (post GL)
  TREAS-->>NATS: treasury.payroll.disbursed
  NATS-->>ERP: consume_events -> mark payslips published
```

---

## 7. Exchange-rate API (FX)

- Config model `integrations/models.py:ExchangeRateAPISettings` (provider, endpoint, **encrypted**
  `access_key` via `integrations/utils.py:Crypto`/Fernet, source + target currencies, schedule).
- Celery Beat task `integrations/tasks.py:fetch_exchange_rates` runs daily 00:00; writes
  `core.ExchangeRate` rows (forward + reverse pairs, `source="api"`). Manual trigger:
  `manual_fetch_exchange_rates`. Default provider `exchangerate.host` (`/live` quotes format).
- This is the only finance-adjacent config the ERP retains (HR/ops currency normalisation).

---

## 8. Branding & taxes (read-through caches)

- `integrations/branding.py:get_tenant_branding(slug)` — fetches auth-api `GET /tenants/by-slug/{slug}`,
  caches 6h. Returns `{name, slug, logo_url, primary_color, secondary_color, kra_pin, address}`.
  The ERP must NOT own a branding editor (auth-api is SoT). Used by document/payslip PDFs + login.
- `integrations/taxes.py` — treasury is SoT for sales tax; cached 1h. (Payroll statutory deductions
  are computed locally — NOT fetched here.)

---

## 9. Contract summary tables

### All event subjects
| Subject | Direction | Counterparty |
|---|---|---|
| `erp.payroll.processed` | OUT | treasury-api |
| `erp.email.requested` | OUT | notifications-api |
| `erp.notification.requested` | OUT | notifications-api |
| `auth.tenant.*` | IN | auth-api |
| `auth.outlet.*` | IN | auth-api |
| `treasury.payroll.disbursed` | IN | treasury-api |

### All S2S HTTP contracts
| Direction | Service | Method Path |
|---|---|---|
| OUT | auth-api | `GET /api/v1/tenants/by-slug/{slug}` |
| OUT | auth-api | `GET /api/v1/tenants/{slug}/outlets` |
| OUT | auth-api | `GET /.well-known/jwks.json` |
| OUT | treasury-api | `GET /api/v1/s2s/{tenant}/taxes` |
| OUT | treasury-api | `GET /api/v1/s2s/{tenant}/taxes/{code}` |
| OUT | treasury-api | `POST /api/v1/s2s/{tenant}/payouts/disburse` |
| IN | (k8s/UI) | `GET /api/v1/core/health/`, `GET /api/v1/integrations/health/`, `GET /api/v1/business/public-branding/`, `GET /api/v1/auth/me/` |

---

## 10. Go revamp mapping

| Django piece | Go replacement |
|---|---|
| `integrations/events.py` + `EventOutbox` + `drain_outbox`/`consume_events` | `shared-events` `OutboxPoller` + NATS consumers in `modules/consumers` against an `outbox_events` Ent table |
| `integrations/service_client.py` | `platform/auth`, `platform/treasury` typed S2S clients (httpware client + `INTERNAL_SERVICE_KEY`) |
| `authmanagement/sso.py` + middleware | `shared-auth-client` (JWKS, Claims, middleware) + `services/usersync` JIT shadow |
| `SubscriptionGatingMiddleware` | `platform/subscriptions` middleware (claims-based, mutations-only) — copy inventory-api |
| `integrations/branding.py` / `taxes.py` | `platform/auth.GetBranding` / `platform/treasury.GetTaxCodes` (Redis-cached) |
| `notifications_client.py` | thin `platform/notifications` publisher (`erp.email.requested` / `erp.notification.requested`) |
| `integrations/tasks.fetch_exchange_rates` (Celery Beat) | cron goroutine / k8s CronJob calling `platform/fx` |
| `treasury_integration.py` | `modules/payroll` finalize step → publish + S2S disburse + consumer |

Keep subjects, payload shapes, and S2S paths byte-compatible so downstream services need no change.
