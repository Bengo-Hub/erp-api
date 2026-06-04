"""
Tenant + outlet syncer — keeps thin local shadows (``authmanagement.AuthTenant`` /
``AuthOutlet``) of the auth-api source of truth.

auth-api owns tenant + outlet/branch identity (shared-docs/sso-integration-guide.md →
Outlet/Branch Context, Tenant UUID single source of truth). The ERP NEVER creates
tenants/outlets; it mirrors them so HR records can reference an outlet UUID and
tenant-scoped queries are fast/offline-safe.

Two sync paths:
  - on-demand pull (JIT): ``ensure_tenant`` / ``sync_outlets`` call the public auth-api
    endpoints (no auth required).
  - push: ``handle_tenant_event`` / ``handle_outlet_event`` consume NATS
    ``auth.tenant.*`` / ``auth.outlet.*`` (registered in integrations.events.run_consumers).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .service_client import ServiceError, get_client

logger = logging.getLogger(__name__)


def ensure_tenant(slug: str = "", tenant_id: str = "", request=None):
    """Return the local AuthTenant shadow, pulling from auth-api if missing.

    Best-effort: returns None on any failure so request handling never breaks.
    """
    from authmanagement.models import AuthTenant

    if tenant_id:
        existing = AuthTenant.objects.filter(id=tenant_id).first()
        if existing:
            return existing
    if slug:
        existing = AuthTenant.objects.filter(slug=slug).first()
        if existing:
            return existing
    if not slug:
        return None
    try:
        client = get_client("auth", request=request)
        data = client.get(f"/api/v1/tenants/by-slug/{slug}")
    except ServiceError as exc:
        logger.warning("ensure_tenant(%s) auth-api lookup failed: %s", slug, exc)
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return _upsert_tenant(data)


def _upsert_tenant(data: dict[str, Any]):
    from authmanagement.models import AuthTenant

    obj, _ = AuthTenant.objects.update_or_create(
        id=data["id"],
        defaults={
            "slug": data.get("slug", "") or "",
            "name": data.get("name", "") or "",
            "status": (data.get("status") or "active"),
            "is_platform": (data.get("slug") == "codevertex"),
        },
    )
    return obj


def sync_outlets(slug: str, tenant_id: str = "", request=None) -> list:
    """Pull the tenant's outlets from auth-api and upsert AuthOutlet shadows."""
    from authmanagement.models import AuthOutlet

    if not slug:
        return []
    try:
        client = get_client("auth", request=request)
        rows = client.get(f"/api/v1/tenants/{slug}/outlets")
    except ServiceError as exc:
        logger.warning("sync_outlets(%s) failed: %s", slug, exc)
        return []
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if isinstance(r, dict) and r.get("id"):
            out.append(_upsert_outlet(r, tenant_id))
    return out


def _upsert_outlet(data: dict[str, Any], tenant_id: str = ""):
    from authmanagement.models import AuthOutlet

    obj, _ = AuthOutlet.objects.update_or_create(
        id=data["id"],
        defaults={
            "tenant_id": data.get("tenant_id") or tenant_id,
            "code": data.get("code", "") or "",
            "name": data.get("name", "") or "",
            "use_case": data.get("use_case", "") or "",
            "is_hq": bool(data.get("is_hq")),
            "status": (data.get("status") or "active"),
            "timezone": data.get("timezone", "") or "Africa/Nairobi",
        },
    )
    return obj


def ensure_outlet_from_claims(claims, tenant_id: str = ""):
    """JIT-upsert the AuthOutlet shadow for the user's CURRENT outlet from the JWT.

    The access token already carries outlet_id/outlet_code/outlet_use_case/is_hq_user
    once an outlet has been selected (sso-integration-guide step 11), so we mirror the
    *active* outlet locally without an extra auth-api round-trip. This guarantees the
    outlet a user is acting in always has a local shadow for HR records to reference.
    (The full outlet list for the selector is pulled directly from auth-api by the UI.)

    Best-effort: returns None and never raises so request handling is never blocked.
    No-op when no outlet is selected (HQ/platform users before outlet selection) or
    when the tenant is unknown (the shadow needs a tenant UUID).
    """
    from authmanagement.models import AuthOutlet

    outlet_id = getattr(claims, "outlet_id", "") or ""
    tid = tenant_id or getattr(claims, "tenant_id", "") or ""
    if not outlet_id or not tid:
        return None
    try:
        # `name` is intentionally omitted from defaults: it is not in the JWT, so we
        # never clobber a richer name set by a full sync_outlets() pull.
        obj, _ = AuthOutlet.objects.update_or_create(
            id=outlet_id,
            defaults={
                "tenant_id": tid,
                "code": getattr(claims, "outlet_code", "") or "",
                "use_case": getattr(claims, "outlet_use_case", "") or "",
                "is_hq": bool(getattr(claims, "is_hq_user", False)),
                "status": "active",
            },
        )
        return obj
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("ensure_outlet_from_claims(%s) failed: %s", outlet_id, exc)
        return None


# ---------------------------------------------------------------------------
# NATS event handlers (registered in integrations.events.run_consumers)
# ---------------------------------------------------------------------------
def handle_tenant_event(envelope: dict[str, Any]) -> None:
    payload = (envelope or {}).get("payload", envelope) or {}
    if payload.get("id") or payload.get("tenant_id"):
        data = {
            "id": payload.get("id") or payload.get("tenant_id"),
            "slug": payload.get("slug") or payload.get("tenant_slug", ""),
            "name": payload.get("name", ""),
            "status": payload.get("status", "active"),
        }
        if data["id"]:
            _upsert_tenant(data)


def handle_outlet_event(envelope: dict[str, Any]) -> None:
    payload = (envelope or {}).get("payload", envelope) or {}
    event_type = (envelope or {}).get("event_type", "")
    from authmanagement.models import AuthOutlet

    outlet_id = payload.get("id") or payload.get("outlet_id")
    if not outlet_id:
        return
    if event_type.endswith("archived"):
        AuthOutlet.objects.filter(id=outlet_id).update(status="archived")
        return
    _upsert_outlet({**payload, "id": outlet_id}, payload.get("tenant_id", ""))
