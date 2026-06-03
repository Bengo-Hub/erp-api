"""
Tenant branding accessor — auth-api is the single source of truth for tenant
branding (logo, colors, KRA PIN, address). Per shared-docs/sso-integration-guide.md
("Do NOT store branding locally or provide a branding editor") and
feedback_document_generation_architecture, services fetch branding from auth-api and
cache it; they never own it.

Used by document generation (payslip/letter PDFs), the login response, and reports so
they show correct tenant branding without the ERP being the system of record.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.core.cache import cache

from .service_client import ServiceError, get_client

logger = logging.getLogger(__name__)

_TTL = 6 * 60 * 60  # 6h, matching JWT/branding cache convention


def get_tenant_branding(slug: str = "", tenant_id: str = "", request=None) -> dict[str, Any]:
    """Return tenant branding from auth-api (cached). Empty dict on failure (callers
    fall back to local defaults so documents/login never break)."""
    key = f"erp:branding:{slug or tenant_id}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    if not slug:
        return {}
    try:
        client = get_client("auth", request=request)
        data = client.get(f"/api/v1/tenants/by-slug/{slug}")
    except ServiceError as exc:
        logger.warning("get_tenant_branding(%s) failed: %s", slug, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    colors = data.get("brand_colors") or {}
    branding = {
        "name": data.get("name", ""),
        "slug": data.get("slug", ""),
        "logo_url": data.get("logo_url", "") or data.get("logo", ""),
        "primary_color": colors.get("primary") or data.get("primary_color", ""),
        "secondary_color": colors.get("secondary") or data.get("secondary_color", ""),
        "kra_pin": data.get("kra_pin", "") or data.get("kra_number", ""),
        "address": data.get("address", ""),
    }
    cache.set(key, branding, _TTL)
    return branding
